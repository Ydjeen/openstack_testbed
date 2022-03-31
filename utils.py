import json
import os

DEPLOY_LIST_FOLDER = "deploy_list/"
DEPLOY_FOLDER_LSTRIP = f"{DEPLOY_LIST_FOLDER}deploy"
RALLY_FOLDER = "rally"
RALLY_FILES_FOLDER = "rally_files"

DATETIME_FORMAT = "%Y.%m.%d %H:%M:%S"
TIME_TO_TASK_NAME = "task_%Y.%m.%d_%H:%M:%S"

PORT_ELASTICSEARCH = 9200

def ensure_folder(folder):
    if not os.path.exists(folder):
        return os.makedirs(folder)


def get_config_folder(config_id):
    folder = f'{DEPLOY_FOLDER_LSTRIP}{config_id}/'
    if not os.path.exists(folder):
        return None
    return folder

def read_json_file(file_path):
    with open(file_path) as json_file:
        return json.load(json_file)
    return None

def get_rally_folder(deployment_id):
    return f"{DEPLOY_FOLDER_LSTRIP}{deployment_id}/{RALLY_FOLDER}/"


def get_experiment_folder(deployment_id, request_name):
    return f"{DEPLOY_FOLDER_LSTRIP}{deployment_id}/{RALLY_FOLDER}/{request_name}/"


def get_load_folder(deployment_id, request_name, load_name):
    return f"{DEPLOY_FOLDER_LSTRIP}{deployment_id}/{RALLY_FOLDER}/{request_name}/{load_name}/"


def get_deployment_folder(deployment_id):
    return f"{DEPLOY_FOLDER_LSTRIP}{deployment_id}/"
