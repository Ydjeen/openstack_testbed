import csv
import json
import pandas as pd

import requests

import utils
from models.deployment import Deployment
from models.node import Node
from utils import *

FOLDER_NO_NAME = "metric_no_name"
METRIC_NO_NAME = "node"
METRIC_COLLECTION_STEP = 10
metric_labels_excluded = ['__name__', 'instance', 'job']


class MetricsCollector:

    def __init__(self, deployment_id, request_name, load_name, start, end):
        self.deployment_id = deployment_id
        self.request_name = request_name
        self.load_name = load_name
        self.start = start
        self.end = end

        self.prometheus_url = self.get_prometheus_url()
        self.load_folder = utils.get_load_folder(self.deployment_id, self.request_name, self.load_name)
        self.metrics_folder = self.load_folder + "/labeled_metrics/"

        with open(self.load_folder + Deployment.RALLY_REPORT_JSON) as jsondata:
            self.rally_report_json = json.load(jsondata)

        self.anomaly_type = None
        self.anomaly_start = None
        self.anomaly_end = None
        if self.fault_injection_used():
            self.anomaly_info = self.rally_report_json['tasks'][0]['subtasks'][0]['workloads'][0]['hooks'][0]
            self.anomaly_type = self.anomaly_info['config']['action']['fault_injection']['anomaly']
            self.anomaly_start = self.anomaly_info['results'][0]['started_at']
            self.anomaly_end = self.anomaly_info['results'][0]['finished_at']
            self.anomaly_delay = self.anomaly_info['config']['action']['fault_injection']["params"].get("delay", {})
            time_unit = self.anomaly_delay[-1:]
            self.anomaly_delay = int(self.anomaly_delay[:-1])
            if time_unit == 'm':
                self.anomaly_delay = self.anomaly_delay * 60
            if time_unit == 'h':
                self.anomaly_delay = self.anomaly_delay * 360
            self.anomaly_start = self.anomaly_start + self.anomaly_delay
            self.anomaly_end = self.anomaly_end + self.anomaly_delay

    def get_prometheus_url(self):
        configuration = Deployment.load(self.deployment_id)
        monitoring_url = configuration.get_monitoring_url()
        return f"{monitoring_url}:9091/"

    def extract_metrics(self):
        instances_with_ports = self.get_label_values("instance")

        instances = list()
        for instance in instances_with_ports:
            instances.append(instance.split(":")[0])
        instances = list(dict.fromkeys(instances))
        names = self.get_label_values("name")
        metrics = self.get_label_values("__name__")

        ensure_folder(self.metrics_folder)
        for instance in instances:
            ensure_folder(self.metrics_folder + instance)
        self.write_custom_metrics(instances)
        self.write_metrics(names, metrics, instances)
        self.folder_ip_to_name(instances)
        return "done"

    def folder_ip_to_name(self, instances):
        nodes = Node.query.filter(Node.deployment_id == self.deployment_id).all()
        for instance in instances:
            for node in nodes:
                if node.ip == instance:
                    os.rename(self.metrics_folder + instance,
                              self.metrics_folder + node.domain)



    def request_prometheus_metric(self, metric, name=None, instance=None):
        arguments = list()
        if name:
            arguments.append(f'name=\"{name}\"')
        if instance:
            arguments.append(f'instance=~\"{instance}.*\"')
        argument_string = ""
        for argument in arguments:
            ###TODO check if this is ever called
            argument_string += argument + ','
        ###TODO
        request_url = f"http://{self.prometheus_url}/api/v1/query_range?query={metric}" \
                      f"&start={self.start.timestamp()}&" \
                      f"end={self.end.timestamp()}&" \
                      f"step={METRIC_COLLECTION_STEP}&" \
                      f"{{{argument_string}}}"
        response = requests.get(request_url)
        return response.json()['data']['result']

    def fault_injection_used(self):
        if not self.rally_report_json:
            return False
        hooks = self.rally_report_json['tasks'][0]['subtasks'][0]['workloads'][0]['hooks']
        fault_injection_in_config = False
        if hooks:
            fault_injection_in_config = 'fault_injection' in hooks[0]['config']['action']
        return fault_injection_in_config

    def write_metrics(self, names, metrics, instances):
        dt_list = {}
        for instance in instances:
            dt_list[METRIC_NO_NAME, instance] = pd.DataFrame()
            for name in names:
                dt_list[name, instance] = pd.DataFrame()
        for metric in metrics:
            respond = self.request_prometheus_metric(metric)
            if respond:
                no_name_metrics = list()
                named_metrics = list()
                for submetric in respond:
                    if not 'job' in submetric['metric'].keys():
                        continue
                    else:
                        if not submetric['metric']['job'] in ['cadvisor', 'node']:
                            continue
                    clear_port(submetric['metric'])
                    if 'name' in submetric['metric'].keys():
                        named_metrics.append(submetric)
                    else:
                        no_name_metrics.append(submetric)
                if named_metrics:
                    self.write_named_metrics(named_metrics, names, metric, instances, dt_list)
                if no_name_metrics:
                    self.write_no_named_metrics(no_name_metrics, names, metric, instances, dt_list)
        ##
        ##
        ##
        for key, dt in dt_list.items():
            if dt.empty: continue
            dt.insert(loc=1, column='label', value=0)
            dt.insert(loc=2, column='anomaly_type', value='-')
            dt.loc[(self.anomaly_start < dt['timestamp']) & (dt['timestamp'] < self.anomaly_end), 'label'] = 1
            dt.loc[(self.anomaly_start < dt['timestamp']) & (dt['timestamp'] < self.anomaly_end), 'anomaly_type'] = self.anomaly_type
            dt.to_csv(self.metrics_folder + '/' + key[1] + '/' + key[0] + '.csv', index=False)

    def write_custom_metrics(self, instances):
        custom_metric_list = utils.read_json_file('openstack_tools/custom_metrics.json')
        dt_list = {}
        for instance in instances:
            dt_list[instance] = pd.DataFrame()
        for metric_name in custom_metric_list:
            try:
                if (metric_name == 'node_avg_memory'):
                    print('alarm')
                respond = self.request_prometheus_metric(custom_metric_list[metric_name])
            except KeyError as e:
                print('error occured at ' + custom_metric_list[metric_name])
                raise(e)
            self.parse_prometheus_metric(dt_list, respond, metric_name)
        for instance in instances:
            dt = dt_list[instance]
            dt.insert(loc=1, column='label', value=0)
            dt.insert(loc=2, column='anomaly_type', value='-')
            dt.loc[(self.anomaly_start < dt['timestamp']) & (dt['timestamp'] < self.anomaly_end), 'label'] = 1
            dt.loc[(self.anomaly_start < dt['timestamp']) & (
                        dt['timestamp'] < self.anomaly_end), 'anomaly_type'] = self.anomaly_type
            dt.to_csv(self.metrics_folder + '/' + instance + '/' + 'custom_metrics.csv', index=False)

    def write_named_metrics(self, named_metrics, names, metric, instances, dt_list):
        metrics_sorted = {}
        for instance in instances:
            metrics_sorted[instance] = {}
        # form a dictionary, in which metrics are grouped by name
        # key - name
        # value - list of metrics grouped by name
        for metric_item in named_metrics:
            meta_info = metric_item['metric']
            if not meta_info['name'] in metrics_sorted[meta_info['instance']]:
                metrics_sorted[meta_info['instance']][meta_info['name']] = list()
            metrics_sorted[meta_info['instance']][meta_info['name']].append(metric_item)
        for instance in metrics_sorted:
            for name in metrics_sorted[instance]:
                dt = dt_list[name, instance]
                ensure_folder(self.metrics_folder + instance + "/")
                metric_group = metrics_sorted[instance][name]
                different_columns = set()
                if len(metric_group) > 1:
                    metric_keys = metric_group[0]['metric'].keys()
                    for submetric in metric_group[1:]:
                        for key in metric_keys:
                            ##TODO THIS MIGHT IGNORE SOME UNIQUE COLUMNS
                            ## SHOULD BE REFACTORED IN THE FUTURE
                            if key in submetric['metric'] and key in metric_group[0]['metric']:
                                if submetric['metric'][key] != metric_group[0]['metric'][key]:
                                    different_columns.add(key)
                for submetric in metric_group:
                    title = metric
                    for label in submetric['metric']:
                        if label in metric_labels_excluded:
                            continue
                        if not label in different_columns:
                            continue
                        title = f'{title}_{submetric["metric"][label]}'
                    df_metric = pd.DataFrame(submetric["values"])
                    df_metric.columns = ['timestamp', title]
                    df_metric.set_index('timestamp')
                    if dt_list[name, instance].empty:
                        dt_list[name, instance] = dt_list[name, instance].append(df_metric)
                    else:
                        if len(df_metric.index) == len(dt_list[name, instance].index):
                            dt_list[name, instance][title] = df_metric[df_metric.columns[1]]
                        else:
                            dt_list[name, instance] = pd.merge(dt_list[name, instance], df_metric,
                                                               on='timestamp', how="outer")

    def write_no_named_metrics(self, no_name_metrics, names, metric, instances, dt_list):
        metrics_sorted = {}
        for instance in instances:
            metrics_sorted[instance] = list()
        for metric_item in no_name_metrics:
            whitelisted_metric = False
            if metric_item['metric']['job'] == 'cadvisor':
                if 'name' in metric_item['metric']:
                    whitelisted_metric = True
            if not 'name' in metric_item['metric']:
                whitelisted_metric = True
            if whitelisted_metric:
                metrics_sorted[metric_item['metric']['instance']].append(metric_item)
        different_columns = set()
        values_view = metrics_sorted.values()
        value_iterator = iter(values_view)
        first_instance = next(value_iterator)
        if len(first_instance) > 1:
            metric_keys = first_instance[0]['metric'].keys()
            for submetric in first_instance[1:]:
                for key in metric_keys:
                    ##TODO THIS MIGHT IGNORE SOME UNIQUE COLUMNS
                    ## SHOULD BE REFACTORED IN THE FUTURE
                    if key in submetric['metric'] and key in first_instance[0]['metric']:
                        if submetric['metric'][key] != first_instance[0]['metric'][key]:
                            different_columns.add(key)
        for instance in metrics_sorted:
            dt = dt_list[METRIC_NO_NAME, instance]
            title = metric
            for submetric in metrics_sorted[instance]:
                title = metric
                for label in submetric['metric']:
                    if label in metric_labels_excluded:
                        continue
                    if not label in different_columns:
                        continue
                    title = f'{title}_{submetric["metric"][label]}'
                df_metric = pd.DataFrame(submetric["values"])
                df_metric.columns = ['timestamp', title]
                df_metric.set_index('timestamp')
                if (dt_list[METRIC_NO_NAME, instance].empty):
                    dt_list[METRIC_NO_NAME, instance] = dt_list[METRIC_NO_NAME, instance].append(df_metric)
                else:
                    if (len(df_metric.index) == len(dt_list[METRIC_NO_NAME, instance].index)):
                        dt_list[METRIC_NO_NAME, instance][title] = df_metric[df_metric.columns[1]]
                    else:
                        dt_list[METRIC_NO_NAME, instance] = pd.merge(dt_list[METRIC_NO_NAME, instance], df_metric,
                                                                     on='timestamp', how="outer")

    def get_label_values(self, label):
        label_values_url = f"http://{self.prometheus_url}api/v1/label/{label}/values"
        response = requests.get(label_values_url)
        values = response.json()['data']
        return values

    def extract_metrics_without_labels(self):
        from openstack_tools import rally_manager
        load_folder = rally_manager.get_load_folder(self.deployment_id, self.request_name, self.load_name)
        instances_with_ports = self.get_label_values("instance")
        instances = list()
        for instance in instances_with_ports:
            instances.append(instance.split(":")[0])
        instances = list(dict.fromkeys(instances))
        names = self.get_label_values("name")
        metrics = self.get_label_values("__name__")
        metrics_folder = load_folder + "/metrics/"
        ensure_folder(metrics_folder)
        for instance in instances:
            ensure_folder(metrics_folder + instance)
        self.write_metrics_without_labels(names, metrics, instances)
        pass

    def write_metrics_without_labels(self, names, metrics, instances):
        for metric in metrics:
            respond = self.request_prometheus_metric(metric)
            if respond:
                no_name_metrics = list()
                named_metrics = list()
                for submetric in respond:
                    clear_port(submetric['metric'])
                    if 'name' in submetric['metric'].keys():
                        named_metrics.append(submetric)
                    else:
                        no_name_metrics.append(submetric)
                # if named_metrics:
                # self.write_named_metrics_without_labels(named_metrics, metrics_folder, names, metric, instances)
                # if no_name_metrics:
                # write_no_named_metrics_without_labels(no_name_metrics, metrics_folder, names, metric, instances)
        pass

    def write_no_named_metrics_without_labels(no_name_metrics, metrics_folder, names, metric, instances):
        metrics_sorted = {}
        for instance in instances:
            metrics_sorted[instance] = list()
        for metric_item in no_name_metrics:
            metrics_sorted[metric_item['metric']['instance']].append(metric_item)

        different_columns = [e for e in list(no_name_metrics[0]['metric'].keys()) if
                             e not in {'__name__', 'instance', 'job'}]
        different_columns = set()
        values_view = metrics_sorted.values()
        value_iterator = iter(values_view)
        first_instance = next(value_iterator)
        if len(first_instance) > 1:
            metric_keys = first_instance[0]['metric'].keys()
            for submetric in first_instance[1:]:
                for key in metric_keys:
                    if submetric['metric'][key] != first_instance[0]['metric'][key]:
                        different_columns.add(key)
        for instance in metrics_sorted:
            ensure_folder(metrics_folder + instance + "/" + FOLDER_NO_NAME)
            writer = csv.writer(open(f"{metrics_folder}{instance}/{FOLDER_NO_NAME}/{metric}.csv", 'w'))
            writer.writerow(list(different_columns) + ['timestamp', 'value'])
            for submetric in metrics_sorted[instance]:
                for base_values in submetric["values"]:
                    full_values = base_values
                    for key in different_columns:
                        full_values.insert(0, submetric['metric'][key])
                    writer.writerow(full_values)

    def write_named_metrics_without_labels(self, named_metrics, metrics_folder, names, metric, instances):
        metrics_sorted = {}
        for instance in instances:
            metrics_sorted[instance] = {}
        # form a dictionary, in which metrics are grouped by name
        # key - name
        # value - list of metrics grouped by name
        for metric_item in named_metrics:
            meta_info = metric_item['metric']
            if not meta_info['name'] in metrics_sorted[meta_info['instance']]:
                metrics_sorted[meta_info['instance']][meta_info['name']] = list()
            metrics_sorted[meta_info['instance']][meta_info['name']].append(metric_item)
        for instance in metrics_sorted:
            for name in metrics_sorted[instance]:
                ensure_folder(metrics_folder + instance + "/" + name)
                metric_group = metrics_sorted[instance][name]
                different_columns = set()
                if len(metric_group) > 1:
                    metric_keys = metric_group[0]['metric'].keys()
                    for submetric in metric_group[1:]:
                        for key in metric_keys:
                            if submetric['metric'][key] != metric_group[0]['metric'][key]:
                                different_columns.add(key)
                writer = csv.writer(open(f"{metrics_folder}{instance}/{name}/{metric}.csv", 'w'))
                writer.writerow(list(different_columns) + ['timestamp', 'value'])
                if different_columns:
                    for submetric in metric_group:
                        for base_values in submetric["values"]:
                            full_values = base_values
                            for key in different_columns:
                                full_values.insert(0, submetric['metric'][key])
                            writer.writerow(full_values)
                else:
                    for line in named_metrics[0]["values"]:
                        writer.writerow(line)

    def parse_prometheus_metric(self, dt_list, respond, metric_name):
        for instance_respond in respond:
            metric_info = instance_respond['metric']
            metric_values = instance_respond['values']
            clear_port(metric_info)
            instance = metric_info['instance']
            unique_colums = list()
            for key in [x for x in metric_info if x not in ['job', 'instance']]:
                unique_colums.append(key)

            submetric_name = metric_name
            for column in unique_colums:
                if metric_info[column] not in metric_name:
                    submetric_name = submetric_name + '_' + metric_info[column]
            dt_instance = dt_list[instance]

            dt_values = pd.DataFrame(metric_values)
            dt_values.columns = ['timestamp', submetric_name]
            dt_values.set_index('timestamp')

            if dt_instance.empty:
                dt_list[instance] = dt_values
            else:
                dt_list[instance] = pd.merge(dt_list[instance], dt_values,
                                             on='timestamp', how="outer")

def ensure_folder(folder):
    if not os.path.exists(folder):
        return os.makedirs(folder)

def clear_port(metric_meta_info):
    metric_meta_info['instance'] = metric_meta_info['instance'].split(":")[0]