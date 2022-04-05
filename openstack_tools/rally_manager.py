import fileinput
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime

import openstack

import utils
from utils import *
from models.deployment import Deployment

FLAVOR_SMALL = 'm1.tiny'
FLAVOR_DEFAULT = FLAVOR_SMALL

ENV_RALLY_OSPROFILER_KEY = "OSPROFILER_HMAC_KEY"

RALLY_HTML_LINE_TO_REPLACE = "ng-repeat=\'str in data track by $index\'>{{str}}"
RALLY_HTML_LINE_REQUIRED = "          var template = \"<div style=\'padding:0 0 5px\' ng-repeat=\'str in data track by $index\'><a href=\\\"{{window.location.href.substr(0, window.location.href.indexOf(\'rally_report\'))}}traces/{{str}}\\\">{{str}}</a></div><div style=\'height:10px\'></div>\";\n"
ANSIBLE_INVENTORY_SEARCHED_LINE = "[controllers]"
FILE_ADMIN_OPENRC = "admin-openrc.sh"

DEPLOYER_FILES_FOLDER = "deployer_files/"
RALLY_TEMPLATE_FOLDER = "rally_files/"
RALLY_COMPLETE_TEMPLATE = "rally_files/complete_test_run_template.yaml"
RALLY_TASK_SOURCE = "task_source.yaml"
RALLY_CONFIG_FILE = "rally.conf"
RALLY_FOLDER = "rally"
RALLY_OUTPUT_HTML = "rally_report.html"
RALLY_OUTPUT_JSON = "rally_report.json"

FILE_RALLY_LOG = "rally_log"
FILE_RALLY_ERROR = "rally_error"

TRACES_HTML_FOLDER = "traces_html"
TRACES_JSON_FOLDER = "traces_json"

CUSTOM_TASK = 'custom_task'

STR_CONCURRENCY = "[concurrency]"
STR_DURATION = "[duration]"
STR_HOOKS = "[hooks]"

ANOMALY_INJECTION_PATH_DICT = {'value':None}

RALLY_TASK_REGEXP = "Task  .*:"

HOOK_BASIC = "      hooks:\n" \
             "        - name: fault_injection\n" \
             "          description: Anomaly\n" \
             "          args: chaos --config_file rally_files/cloud_config.json admin node list\n" \
             "          trigger:\n" \
             "            name: event\n" \
             "            args:\n" \
             "              unit: iteration\n" \
             "              at: [ 1 ]"


def init_rally():
    subprocess.run(["rally", "db", "ensure"], stdin=subprocess.PIPE)

def get_anomaly_injection_path():
    if ANOMALY_INJECTION_PATH_DICT['value']:
        return ANOMALY_INJECTION_PATH_DICT['value']
    for root, dirs, files in os.walk("venv/lib/"):
        for file in files:
            if 'anomaly_injection' in root and file.endswith("rally_plugin.py"):
                ANOMALY_INJECTION_PATH_DICT['value'] = os.path.join(root, file)
                return ANOMALY_INJECTION_PATH_DICT['value']
            ###TODO: FIX venv39 path
    for root, dirs, files in os.walk("venv39/lib/"):
        for file in files:
            if 'anomaly_injection' in root and file.endswith("rally_plugin.py"):
                ANOMALY_INJECTION_PATH_DICT['value'] = os.path.join(root, file)
                return ANOMALY_INJECTION_PATH_DICT['value']
    return None


def get_openstack_env(config_id):
    deploy_folder = f"deploy_list/deploy{config_id}/"
    my_env = os.environ.copy()
    with open(f'{deploy_folder}admin-openrc.sh') as input_file:
        for line in input_file:
            if 'export' not in line:
                continue
            line = line.rstrip('\n')
            line = line.lstrip('export ')
            key, value = line.split('=')
            my_env[key] = value
    with open(f'{deploy_folder}passwords.yml') as input_file:
        for line in input_file:
            if "osprofiler_secret" in line:
                line = line.rstrip('\n')
                osprofiler_key = line.lstrip('osprofiler_secret: ')
                my_env[ENV_RALLY_OSPROFILER_KEY] = osprofiler_key
    os.environ.update(my_env)


def create_deployment(config_id):
    deploy_folder = f"deploy_list/deploy{config_id}/"
    if not os.path.exists(f"{deploy_folder}{FILE_ADMIN_OPENRC}"):
        return
    file_log = open(f"{deploy_folder}rally_log", "a+")
    file_log.flush()
    get_openstack_env(config_id)
    subprocess.run(["rally", "deployment", "destroy", f"deployment{config_id}"], stdin=subprocess.PIPE,  stdout=file_log)
    subprocess.run(["rally", "deployment", "create", "--fromenv", f"--name=deployment{config_id}"], stdin=subprocess.PIPE, stdout=file_log)


def add_trace_hrefs_to_rally(deploy_id, load_folder):
    counter = 0
    for line in fileinput.input(
            f"{load_folder}{RALLY_OUTPUT_HTML}", inplace=True):
        counter = counter + 1
        if counter == 168:
            counter = counter
        if line.find(RALLY_HTML_LINE_TO_REPLACE) != -1:
            sys.stdout.write(
                RALLY_HTML_LINE_REQUIRED
            )
        else:
            sys.stdout.write(line)
    pass


def create_image(config_id, conf_env):
    conn = openstack.connect()
    image = conn.get_image("TestVM")
    if image:
        return
    subprocess.run(
        ['openstack', 'flavor', 'create', '--public', FLAVOR_DEFAULT, '--id', 'auto', '--ram', '512', '--disk', '1',
         '--vcpus', '1'], stdin=subprocess.PIPE)
    if not os.path.exists('cirros-0.3.4-x86_64-disk.img'):
        subprocess.run(['wget', 'http://downloacirros-cloud.net/0.3.4/cirros-0.3.4-x86_64-disk.img'], stdin=subprocess.PIPE)
    subprocess.run(
        ['openstack', 'image', 'create', 'TestVM', '--file', 'cirros-0.3.4-x86_64-disk.img', '--disk-format', 'qcow2',
         '--container-format', 'bare', '--public'], stdin=subprocess.PIPE)


def openstack_image_exists(config_id, name):
    get_openstack_env(config_id)
    output = subprocess.run(['openstack', 'image', 'list'], capture_output=True, stdin=subprocess.PIPE)
    return output


def compress_output_data(deployment_id, request_name):
    experiment_folder = get_experiment_folder(deployment_id, request_name)
    rally_folder = get_rally_folder(deployment_id)
    shutil.make_archive(experiment_folder, 'zip', rally_folder, request_name)


def extract_traces(deployment_id, request_name, load_name):
    load_folder = get_load_folder(deployment_id, request_name, load_name)
    html_folder = load_folder + TRACES_HTML_FOLDER
    json_folder = load_folder + TRACES_JSON_FOLDER
    if not os.path.exists(html_folder):
        os.makedirs(html_folder)
    if not os.path.exists(json_folder):
        os.makedirs(json_folder)

    with open(load_folder + Deployment.RALLY_REPORT_JSON) as jsondata:
        json_data = json.load(jsondata)
    traces = list()
    for task in json_data['tasks']:
        for subtask in task['subtasks']:
            for workload in subtask['workloads']:
                for iteration in workload['data']:
                    for complete in iteration['output']['complete']:
                        traces.append(complete['data']['trace_id'])
    depl = Deployment.load(deployment_id)
    for trace in traces:
        html_output_file = open(f"{html_folder}/{trace}.html", "a+")
        subprocess.run(["osprofiler", "trace", "show", "--html", trace, "--connection-string",
                        f"elasticsearch://{depl.get_control_url()}:9200"], stdin=subprocess.PIPE, stdout=html_output_file)
        html_output_file.close()

        json_output_file = open(f"{json_folder}/{trace}.json", "a+")
        subprocess.run(["osprofiler", "trace", "show", "--json", trace, "--connection-string",
                        f"elasticsearch://{depl.get_control_url()}:9200"], stdin=subprocess.PIPE, stdout=json_output_file)
        json_output_file.close()
    return {"traces": traces}


# depreciated
def start_data_collection(config_id):
    subprocess.run(["./deploy_bitfflow_collector/generate-inventory.sh"], stdin=subprocess.PIPE)
    configuration = Deployment.load(config_id)
    ### TODO Remove or fix controle node information
    line_to_insert = f'wally0{configuration.control[0]} ansible_host=130.149.249.{configuration.control[0] + 10} zone=nova host_type=control'
    for line in fileinput.input(f"{DEPLOY_FOLDER_LSTRIP}{config_id}/ansible-inventory.ini", inplace=True):
        sys.stdout.write(line)
        if line.find(ANSIBLE_INVENTORY_SEARCHED_LINE) != -1:
            sys.stdout.write(ANSIBLE_INVENTORY_SEARCHED_LINE)
    subprocess.run(["./deploy_bitflow_collector/scripts/data-collection/enable-data-collection.yml"], stdin=subprocess.PIPE)


# depreciated
def stop_data_collection(config_id):
    subprocess.run(["./deploy_bitflow_collector/scripts/data-collection/stop-data-collection.yml"])
    subprocess.run(["./deploy_bitflow_collector/scripts/data-collection/fetch-data.yml"])
    subprocess.run(["./deploy_bitflow_collector/scripts/data-collection/clean-remote-data.yml"])
    pass


# depreciated
def data_collection_debug(config_id):
    get_openstack_env(config_id)
    start_data_collection(config_id)
    time.sleep(30)
    stop_data_collection(config_id)


def extract_logs(deployment_id, task_name, load_name, time_start, time_end):
    load_folder = f"{get_load_folder(deployment_id, task_name, load_name)}/"
    time_start_string = time_start.strftime("%Y-%m-%dT%H:%M:00")
    time_end_string = time_end.strftime("%Y-%m-%dT%H:%M:59")
    deployment = Deployment.query.filter(Deployment.id == deployment_id).first()
    search_body = "{\"query\":{\"range\":{\"@timestamp\":{\"gte\":\"" + time_start_string + "\",\"lt\":\"" \
                  + time_end_string + "\",\"time_zone\":\"+02:00\"}}}}"
    subprocess.run(["./node_modules/elasticdump/bin/elasticdump",
                    f"--input=http://{deployment.get_control_url()}:9200/flog-*",
                    f"--output={load_folder}{Deployment.LOG_DUMP}", "--overwrite", f"--searchBody={search_body}"], stdin=subprocess.PIPE)
    print(search_body)
    # "--searchBody=\"{\\\"query\\\":{\\\"range\\\":{\\\"@timestamp\\\":{\\\"gte\\\":\\\"2020-08-31T11:00:00\\\",\\\"lt\\\":\\\"2020-08-31T11:10:00\\\"}}}}\""
    pass


def prepare_custom_load(config_id, load_code):
    deploy_folder = f"{DEPLOY_FOLDER_LSTRIP}{config_id}/"
    rally_folder = deploy_folder + "output/"
    task_folder = deploy_folder + RALLY_FOLDER
    if not os.path.exists(task_folder):
        os.makedirs(task_folder)
    custom_task_file = task_folder + "task" + datetime.now().strftime("%d.%m.%y_%X")
    with open(custom_task_file, "w+") as text_file:
        text_file.write(load_code)
    return custom_task_file


def prepare_load(deploy_id, name, kwargs):
    deploy_folder = f"{DEPLOY_FOLDER_LSTRIP}{deploy_id}/"
    rally_folder = deploy_folder + RALLY_FOLDER + name + "/"
    task_input = f"{rally_folder}{RALLY_TASK_SOURCE}"
    if not os.path.exists(rally_folder):
        os.makedirs(rally_folder)
    shutil.copyfile(RALLY_COMPLETE_TEMPLATE,
                    task_input)
    with fileinput.FileInput(task_input, inplace=True) as file:
        for line in file:
            print(line.replace(STR_CONCURRENCY, kwargs['concurrency']) \
                  .replace(STR_DURATION, kwargs['duration'])
                  .replace(STR_HOOKS, kwargs['hooks']), end='')
    return


def get_full_html_report_file(deploy_id, task_name):
    experiment_folder = get_experiment_folder(deploy_id, task_name)
    return experiment_folder + RALLY_OUTPUT_HTML


def get_html_report_file(deploy_id, task_name, load_id):
    load_folder = get_load_folder(deploy_id, task_name, load_id)
    return load_folder + RALLY_OUTPUT_HTML


def get_json_report_file(deploy_id, task_name, load_id):
    load_folder = get_load_folder(deploy_id, task_name, load_id)
    return load_folder + RALLY_OUTPUT_JSON


def get_log_file(deploy_id, task_name, load_id):
    load_folder = get_load_folder(deploy_id, task_name, load_id)
    return load_folder + FILE_RALLY_LOG


def get_error_file(deploy_id, task_name, load_id):
    load_folder = get_load_folder(deploy_id, task_name, load_id)
    return load_folder + FILE_RALLY_ERROR


def get_rally_folder(deployment_id):
    return f"{DEPLOY_FOLDER_LSTRIP}{deployment_id}/{RALLY_FOLDER}/"


def get_experiment_folder(deployment_id, request_name):
    return f"{DEPLOY_FOLDER_LSTRIP}{deployment_id}/{RALLY_FOLDER}/{request_name}/"


def get_load_folder(deployment_id, request_name, load_name):
    return f"{DEPLOY_FOLDER_LSTRIP}{deployment_id}/{RALLY_FOLDER}/{request_name}/{load_name}/"


def get_deployment_folder(deployment_id):
    return f"{DEPLOY_FOLDER_LSTRIP}{deployment_id}/"


def get_traces_html_file(deployment_id, request_name, load_name, trace_file_id):
    return f"{get_load_folder(deployment_id, request_name, load_name)}/{TRACES_HTML_FOLDER}/{trace_file_id}.html"


def get_full_dump_file(config_id, request_id):
    return f"{get_rally_folder(config_id)}/{request_id}"


def verify_task(deployment_id, load_folder):
    output = subprocess.run(["rally",
                             "--config-file", "rally_files/rally.conf",
                             "--plugin-paths",
                             "rally_files/complete_test_run.py," + get_anomaly_injection_path(),
                             "task", "validate",
                             f'{load_folder}/{RALLY_TASK_SOURCE}',
                             "--deployment", f"deployment{deployment_id}"],
                            capture_output=True, stdin=subprocess.PIPE, text=True)
    if output.returncode == 0:
        return True
    with open(f'{load_folder}/{FILE_RALLY_ERROR}', "w+") as text_file:
        text_file.write(output.stdout)
    return False


def get_task_name(file_path):
    # Strips the newline character
    rally_log_file = open(file_path, 'r')
    lines = rally_log_file.readlines()
    for line in lines:
        match_result = re.match(RALLY_TASK_REGEXP, line)
        if match_result:
            return match_result.group()[6:-1]


def run_load(deployment_id, request_name, load_name, workload, config):
    experiment_folder = get_experiment_folder(deployment_id, request_name)
    load_folder = get_load_folder(deployment_id, request_name, load_name)
    utils.ensure_folder(load_folder)
    task_file = load_folder + RALLY_TASK_SOURCE
    config_file = load_folder + RALLY_CONFIG_FILE
    with open(task_file, "w+") as text_file:
        text_file.write(workload)
    with open(config_file, "w+") as text_file:
        text_file.write(config)
    if not verify_task(deployment_id, load_folder):
        return False
    file_log_path = f"{load_folder}{FILE_RALLY_LOG}"
    file_log = open(file_log_path, "a+")
    file_log.flush()
    shutil.copyfile(get_deployment_folder(deployment_id) + '/multinode', load_folder + '/multinode')
    rally_run_arguments = ["rally",
                    "--config-file", RALLY_CONFIG_FILE,
                    "--plugin-paths", "../../../../../rally_files/complete_test_run.py,"
                    + '../../../../../' + get_anomaly_injection_path(),
                    "task", "start",
                    RALLY_TASK_SOURCE,
                    "--deployment", f"deployment{deployment_id}"]
    file_log.write('executing rally command: '+ ' '.join(rally_run_arguments))
    subprocess.run(rally_run_arguments,
                   cwd=load_folder,
                   stdin=subprocess.PIPE,
                   stdout=file_log)
    task_name = get_task_name(file_log_path)
    subprocess.run(["rally", "task", "report", task_name, "--out",
                    RALLY_OUTPUT_HTML],
                   cwd=load_folder,
                   stdin=subprocess.PIPE,
                   stdout=file_log)
    subprocess.run(
        ["rally", "task", "report", task_name, "--json", "--out", RALLY_OUTPUT_JSON],
        cwd=load_folder, stdin=subprocess.PIPE, stdout=file_log)
    add_trace_hrefs_to_rally(deployment_id, load_folder)
    subprocess.run(
        ["rally", "task", "report", "--deployment", f"deployment{deployment_id}", "--out", RALLY_OUTPUT_HTML],
        cwd=experiment_folder, stdin=subprocess.PIPE, stdout=file_log)
    return True


def get_experiment_results(config_id, task_name):
    experiment_folder = get_experiment_folder(config_id, task_name)
    result = list()
    if not os.path.exists(experiment_folder):
        return result
    list_subfolders = [f.name for f in os.scandir(experiment_folder) if f.is_dir()]
    for folder in list_subfolders:
        load_folder = get_load_folder(config_id, task_name, folder)
        output_present = os.path.exists(f'{load_folder}/{RALLY_OUTPUT_HTML}')
        error_present = os.path.exists(f'{load_folder}/{FILE_RALLY_ERROR}')
        log_present = os.path.exists(f'{load_folder}/{FILE_RALLY_LOG}')
        result.append((folder, log_present, output_present, error_present))
    return result
