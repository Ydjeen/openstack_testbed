import logging
import re
import subprocess
from datetime import datetime, timedelta
import random

import jinja2
from jinja2 import Environment, BaseLoader

from models.deployment import Deployment
from openstack_tools import rally_manager, metrics_collector
from openstack_tools.metrics_collector import MetricsCollector
from utils import get_load_folder

RANDOM_NODE_STRING = "[random_node]"
NODE_LIST_STRING = "[node_list]"
LOAD_FOLDER_NAME = "load"

class ExperimentManager:
    def __init__(self, deployment_id, request_name, kwargs):
        self.deployment_id = deployment_id
        self.request_name = request_name
        self.duration = kwargs['duration']
        workload_source = kwargs['workload']
        self.use_traces = False
        if 'use_traces' in kwargs:
            if kwargs['use_traces'] == 'on':
                self.use_traces = True
        self.workload_template = Environment(loader=BaseLoader).from_string(workload_source)
        self.hooks = list()
        for item in kwargs.items():
            if 'anomaly' in item[0]:
                self.hooks.append(item[1])
        rally_manager.create_deployment(deployment_id)

    def execute(self):
        if not self.duration:
            self.__execute_each_anomaly_once__()
        else:
            import re
            iterations_pattern = "^\d+$"
            ###TODO improve pattern matching
            if re.match(iterations_pattern, self.duration):
                self.__execute_by_iterations__()
            else:
                self.__execute_by_time__()
        rally_manager.compress_output_data(self.deployment_id, self.request_name)

    def __execute_by_iterations__(self):
        iteration = 0
        while (iteration < int(self.duration)):
            if not self.hooks:
                self.execute_load(f'load{iteration}')
            else:
                self.execute_load(f'load{iteration}', random.choice(self.hooks))
            iteration = iteration + 1

    def __execute_by_time__(self):
        self.start_time = datetime.now()
        h = re.search("^\d+h$", self.duration)
        hours = 0
        if (h):
            hours = int(h.group()[:-1])
        m = re.search("^\d+m$", self.duration)
        minutes = 0
        if (m):
            minutes = int(m.group()[:-1])
        d = re.search("^\d+d$", self.duration)
        days = 0
        if (d):
            days = int(d.group()[:-1])
        time_boundary = self.start_time + timedelta(days=days, hours=hours, minutes=minutes)
        current_time = self.start_time
        counter = 0
        while current_time < time_boundary:
            if not self.hooks:
                self.execute_load(f'load{counter}')
            else:
                self.execute_load(f'load{counter}', random.choice(self.hooks))
            counter = counter + 1
            current_time = datetime.now()
        pass

    def __execute_each_anomaly_once__(self):
        chosen_hook = ""
        if not self.hooks:
            return self.execute_load()
        counter = 0
        for hook in self.hooks:
            if not self.execute_load(f'counter{counter}', hook):
                return False
            counter = counter + 1
        return True

    def extract_openstack_logs(self, load_name):
        load_folder = get_load_folder(self.deployment_id, self.request_name, load_name)

        file_log = open(f"{load_folder}experiment_log", "a")

        bootstrap_ansible_cmd = ["ansible-playbook",
                                 "--inventory", f"{load_folder}/multinode", '-vvvv',
                                 f"rally_files/collect_openstack_logs.yaml"]
        try:
            subprocess.run(bootstrap_ansible_cmd, stdout=file_log)
        except subprocess.CalledProcessError as e:
            logging.error("Pre-bootstrapping failed. Check {} for additional information. Error code: {}. "
                          "Error message {}", file_log, e.returncode, e.output)

    def execute_load(self, load_name = 'load0', hook=""):
        hook_template = Environment(loader=BaseLoader).from_string(hook)
        hook_source = hook_template.render()

        deployment: Deployment = Deployment.load(self.deployment_id)
        random_domain_name = f'"{random.choice(deployment.nodes).domain}"'
        hook_source = hook_source.replace(RANDOM_NODE_STRING, random_domain_name)

        node_list = "["
        for node in deployment.nodes:
            node_list += f'"{node.domain}"'
            if not node == deployment.nodes[-1]:
                node_list += ','
        node_list += "]"
        hook_source = hook_source.replace(NODE_LIST_STRING, node_list)

        workload = self.workload_template.render() + '\n' + hook_source

        templateLoader = jinja2.FileSystemLoader(searchpath="./rally_files")
        templateEnv = jinja2.Environment(loader=templateLoader)
        TEMPLATE_FILE = "rally.conf"
        template = templateEnv.get_template(TEMPLATE_FILE)
        rally_config = template.render(use_traces=self.use_traces)

        start_time = datetime.now()
        task_done = rally_manager.run_load(self.deployment_id, self.request_name, load_name, workload, rally_config)
        if not task_done:
            return False
        end_time = datetime.now()
        if self.use_traces:
            rally_manager.extract_traces(self.deployment_id, self.request_name, load_name)
        rally_manager.extract_logs(self.deployment_id, self.request_name, load_name, start_time, end_time)
        print([self.deployment_id, self.request_name, load_name, start_time,
                                          end_time])
        metrics_collector = MetricsCollector(self.deployment_id, self.request_name, load_name, start_time,
                                          end_time)
        metrics_collector.extract_metrics()
        self.extract_openstack_logs(load_name)
        return True