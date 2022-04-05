import datetime
import fileinput
import json
import os
import shutil
import subprocess
import logging
from time import sleep

import openstack
import requests
from keystoneauth1.exceptions import ConnectFailure
from requests.structures import CaseInsensitiveDict

import utils
from app import db
from models.deployment import Deployment
from openstack_tools import rally_manager

STR_CONTROL_IDS = "[control_ids]"
STR_MONITORING_IDS = "[monitoring_ids]"
STR_COMPUTE_IDS = "[compute_ids]"
STR_CONTROL_IP = "[control_ip]"
STR_CONFIG_DIR = "[config_dir]"

FILE_GLOBALS = "globals.yml"
FILE_MULTINODE = "multinode"
FILE_PASSWORDS = "passwords.yml"
FILE_BOOTSTRAP = "bootstrap.yml"
FILE_ANSIBLE_CFG = "ansible.cfg"
DEPLOYER_FILES_FOLDER = "deployer_files/"

MAPPING_OSPROFILER = \
    "{\"mappings\" :{ \"notification\" :{ \"properties\" : {\"info\":{"\
       	"\"properties\":{\"db\":{\"properties\":{\"params\":{\"properties\":{\"id_1\":{\"type\":\"text\"}}}}}}"\
    "}}}}}"

def prepare_config_files(deploy_id):
    deploy = Deployment.load(deploy_id)
    deploy_folder = f"deploy_list/deploy{deploy.id}/"
    utils.ensure_folder(deploy_folder)
    shutil.copyfile(DEPLOYER_FILES_FOLDER + FILE_MULTINODE,
                    f"{deploy_folder}multinode")
    string_compute_ids = ""
    for node in deploy.get_compute_nodes():
        string_compute_ids += f"{node.domain}\n"
    string_control_id = ""
    string_control_id += f"{deploy.get_control_node().domain}\n"
    string_monitoring_id = ""
    string_monitoring_id += f"{deploy.get_monitoring_node().domain}\n"
    with fileinput.FileInput(f"{deploy_folder}multinode", inplace=True) as file:
        for line in file:
            print(line.replace(STR_CONTROL_IDS, string_control_id) \
                  .replace(STR_MONITORING_IDS, string_monitoring_id) \
                  .replace(STR_COMPUTE_IDS, string_compute_ids), end='')
    shutil.copyfile(DEPLOYER_FILES_FOLDER + FILE_GLOBALS,
                    f"{deploy_folder}globals.yml")
    with fileinput.FileInput(f"{deploy_folder}globals.yml", inplace=True) as file:
        for line in file:
            to_print = line.replace(STR_CONTROL_IP, deploy.get_control_node().ip)
            to_print = to_print.replace(STR_CONFIG_DIR, f'{os.getcwd()}/custom_config')
            print(to_print, end='')
    shutil.copyfile(f"{DEPLOYER_FILES_FOLDER}/passwords.yml", f"{deploy_folder}passwords.yml")
    subprocess.run(["kolla-genpwd", "-p", f"{deploy_folder}passwords.yml"])
    shutil.copyfile(f"{DEPLOYER_FILES_FOLDER}/{FILE_BOOTSTRAP}", f"{deploy_folder}{FILE_BOOTSTRAP}")
    shutil.copyfile(f"{DEPLOYER_FILES_FOLDER}/{FILE_ANSIBLE_CFG}", f"{deploy_folder}{FILE_ANSIBLE_CFG}")

def bootstrap_deployment(deploy_id):
    deploy_folder = f"deploy_list/deploy{deploy_id}/"

    deploy = Deployment.load(deploy_id)

    deploy.deploy_start = str(datetime.datetime.now())

    file_log = open(f"{deploy_folder}log", "a")

    bootstrap_ansible_cmd = ["ansible-playbook",
                             "--inventory", f"{deploy_folder}{FILE_MULTINODE}", '-vvvv',
                             f"{deploy_folder}{FILE_BOOTSTRAP}"]
    try:
        subprocess.run(bootstrap_ansible_cmd, stdout=file_log)
    except subprocess.CalledProcessError as e:
        logging.error("Pre-bootstrapping failed. Check {} for additional information. Error code: {}. "
                      "Error message {}", file_log, e.returncode, e.output)


def prepare_elasticsearch(config_id):
    deploy = Deployment.load(config_id)
    index_url = deploy.get_connection_string() + "/osprofiler-notifications"
    r = requests.delete(index_url)
    index_url = index_url + "?pretty"
    headers = CaseInsensitiveDict()
    headers["Content-Type"]="application/json"
    data = MAPPING_OSPROFILER
    r = requests.put(index_url, headers=headers, data=data)
    return "elasticsearch prepared"



def deploy_config(config_id):
    deploy_folder = f"deploy_list/deploy{config_id}/"

    deploy = Deployment.load(config_id)

    deploy.deploy_start = str(datetime.datetime.now())

    file_log = open(f"{deploy_folder}log", "a")

    bootstrap_ansible_cmd = ["ansible-playbook",
                             "--inventory", f"{deploy_folder}{FILE_MULTINODE}",
                             f"{deploy_folder}{FILE_BOOTSTRAP}"]
    try:
        subprocess.run(bootstrap_ansible_cmd, stdout=file_log)
    except subprocess.CalledProcessError as e:
        logging.error("Pre-bootstrapping failed. Check {} for additional information. Error code: {}. "
                      "Error message {}", file_log, e.returncode, e.output)

    """kolla_ansible_cmd_base = ["kolla-ansible",
                              "--inventory", f"{deploy_folder}{FILE_MULTINODE}",
                              "--playbook", f"{deploy_folder}{FILE_GLOBALS}",
                              ]"""
    kolla_ansible_cmd_base = ["kolla-ansible",
                              "--passwords", f"{deploy_folder}{FILE_PASSWORDS}",
                              "--configdir", f"{deploy_folder}",
                              "--inventory", f"{deploy_folder}{FILE_MULTINODE}"
                              ,"-vvvv"]

    try:
        subprocess.run(kolla_ansible_cmd_base + ["bootstrap-servers"], stdout=file_log)
    except subprocess.CalledProcessError as e:
        logging.error("Bootstrapping servers failed. Check {} for additional information. Error code: {}. "
                      "Error message {}", file_log, e.returncode, e.output)

    # TODO when prechecks fail abord deployment and generate report
    # subprocess.run(kolla_ansible_cmd_base + ["prechecks"], stdout=file_log)
    try:
        subprocess.run(kolla_ansible_cmd_base + ["deploy"], stdout=file_log)
    except subprocess.CalledProcessError as e:
        logging.error("Kolla deployment failed. Check {} for additional information. Error code: {}. "
                      "Error message {}", file_log, e.returncode, e.output)

    try:
        subprocess.run(["kolla-ansible",
                        "--passwords", f"{deploy_folder}{FILE_PASSWORDS}",
                        "--configdir", f"{os.getcwd()}/{deploy_folder}",
                        "--inventory", f"{deploy_folder}{FILE_MULTINODE}"]
                       + ["post-deploy"], stdout=file_log)
    except subprocess.CalledProcessError as e:
        logging.error("Kolla post-deployment script failed. Check {} for additional information. Error code: {}. "
                      "Error message {}", file_log, e.returncode, e.output)
    subprocess.run(["sudo", "chmod", "a+r", f"{deploy_folder}/admin-openrc.sh"])
    deploy.deploy_end = str(datetime.datetime.now())
    deploy.state = deploy.STATE_DEPLOYED
    db.session.commit()
    prepare_openstack(config_id)
    prepare_elasticsearch(config_id)

def prepare_openstack(deploy_id):
    rally_manager.get_openstack_env(deploy_id)
    connection = openstack.connect()
    if not connection.get_flavor('m1.tiny'):
        connection.create_flavor('m1.tiny', 512, 1, 1)
    if not connection.get_flavor('m1.small'):
        connection.create_flavor('m1.small', 2048, 1, 20)
    if not connection.get_image('default_image'):
        connection.create_image('default_image',
                            './cirros-0.3.4-x86_64-disk.img',
                            container_format="bare", disk_format="qcow2", visibility="public" )
    if not connection.get_image('corrupted_image'):
        connection.create_image('corrupted_image',
                            './cirros-0.3.4-x86_64-disk_corrupted.img',
                            container_format="bare", disk_format="qcow2", visibility="public" )
    connection.close()
    return "openstack prepared"

def clear_openstack(config_id):
    rally_manager.get_openstack_env(config_id)
    try:
        connection = openstack.connect()
    except ConnectionRefusedError as e:
        return
    try:
        for server in connection.list_servers():
            connection.delete_server(server.__getitem__('id'))
        for volume in connection.list_volumes():
            connection.delete_volume(volume.name)
        for floating_ip in connection.list_floating_ips():
            connection.delete_floating_ip(floating_ip.id)
        for port in connection.list_ports():
            connection.delete_port(port.id)
        for router in connection.list_routers():
            connection.delete_router(router.id)
        for subnet in connection.list_subnets():
            connection.delete_subnet(subnet.id)
        for network in connection.list_networks():
            connection.delete_network(network.id)
        for image in connection.list_images():
            connection.delete_image(image.id)
    except ConnectFailure as e:
        return

def redeploy_config(config_id):
    deployment = Deployment.load(config_id)
    if not deployment.is_destroyed():
        destroy_config(config_id)
    deploy_config(config_id)


def destroy_config(config_id):
    # TODO
    # this has to be done only if openstack is reachable
    clear_openstack(config_id)
    deploy_folder = f"deploy_list/deploy{config_id}/"
    file_log = open(f"{deploy_folder}log", "a")
    kolla_ansible_cmd_base = ["kolla-ansible",
                              "--passwords", f"{deploy_folder}{FILE_PASSWORDS}",
                              "--configdir", f"{deploy_folder}",
                              "--inventory", f"{deploy_folder}{FILE_MULTINODE}"]
    try:
        subprocess.run(kolla_ansible_cmd_base + ["stop", "--yes-i-really-really-mean-it"],
                   stdout=file_log)
    except subprocess.CalledProcessError as e:
        logging.error("Kolla post-deployment script failed. Check {} for additional information. Error code: {}. "
                      "Error message {}", file_log, e.returncode, e.output)
    try:
        subprocess.run(kolla_ansible_cmd_base + ["destroy", "--yes-i-really-really-mean-it"],
                   stdout=file_log)
    except subprocess.CalledProcessError as e:
        logging.error("Kolla post-deployment script failed. Check {} for additional information. Error code: {}. "
                      "Error message {}", file_log, e.returncode, e.output)
    config = Deployment.load(config_id)
    config.state = config.STATE_DESTROYED

    db.session.commit()

def delete_deployment(deploy_id):
    deployment: Deployment = Deployment.query.filter(Deployment.id == deploy_id).first()
    if not deployment.can_be_deleted():
        return
    for node in list(deployment.nodes):
        node.control = False
        node.compute = False
        deployment.nodes.remove(node)
    Deployment.query.filter(Deployment.id == deploy_id).delete()
    db.session.commit()
    if os.path.isdir(f"deploy_list/deploy{deploy_id}/"):
        shutil.rmtree(f"deploy_list/deploy{deploy_id}/")

@staticmethod
def parse_admin_openrc_to_json(config_id):
    deploy_folder = f"deploy_list/deploy{config_id}/"
    input_dict = {}
    with open(f'{deploy_folder}admin-openrc.sh') as inpute_file:
        next(inpute_file)
        next(inpute_file)
        for line in inpute_file:
            line = line.rstrip('\n')
            line = line.lstrip('export ')
            key, value = line.split('=')
            input_dict[key] = value
    admin_info = {'openstack':
                      {"auth_url": input_dict['OS_AUTH_URL'],
                       "region_name": input_dict["OS_REGION_NAME"],
                       "endpoint_type": input_dict["OS_ENDPOINT_TYPE"],
                       "admin": {"username": input_dict['OS_USERNAME'],
                                 'password': input_dict['OS_PASSWORD'],
                                 'tenant_name': input_dict['OS_TENANT_NAME']},
                       "https_insecure": False,
                       "https_cacert": ""}
                  }
    with open(f"{deploy_folder}admin-openrc.json", 'w') as outfile:
        json.dump(admin_info, outfile)


def get_deploy_log(config_id):
    return f"deploy_list/deploy{config_id}/"+'log'

def node_restart(deploy_id, kwargs):
    node = kwargs['node']
    deploy = Deployment.load(deploy_id)
    deploy_folder = f"deploy_list/deploy{deploy.id}/"
    file_log = open(f"{deploy_folder}{node}_log", "a")
    rally_manager.get_openstack_env(deploy_id)
    connection = openstack.connect()
    print(f"Disabling {node}")
    file_log.write("Starting_Maintenance\n")
    file_log.flush()
    try:
        subprocess.run(["openstack", "compute", "service", "set", "--disable", node, "nova-compute"],
        stdout=file_log)
    except subprocess.CalledProcessError as e:
        logging.error("Kolla post-deployment script failed. Check {} for additional information. Error code: {}. "
                      "Error message {}", file_log, e.returncode, e.output)
    waiting_time = 15
    while len(connection.list_servers(filters={"host": node})) > 0:
        sleep(waiting_time)
        waiting_time = waiting_time * 2 if waiting_time < 60 else waiting_time
    file_log.write("Maintenance done!\n")
    file_log.flush()
    try:
        subprocess.run(["openstack", "compute", "service", "set", "--enable", node, "nova-compute"],
        stdout=file_log)
    except subprocess.CalledProcessError as e:
        logging.error("Kolla post-deployment script failed. Check {} for additional information. Error code: {}. "
                      "Error message {}", file_log, e.returncode, e.output)
