import json

from flask import Blueprint, request, render_template, jsonify, send_from_directory, redirect, url_for, send_file, \
    Response
from flask_restful import reqparse, inputs

from models.node import Node

config_blueprint = Blueprint('configs', __name__, url_prefix='/configs')

import app
from models.deployment import Deployment
from cloud_components.request_executor import RequestExecutor
from utils import DEPLOY_FOLDER_LSTRIP

config_parser = reqparse.RequestParser()
config_parser.add_argument("control", action='append', type=str)
config_parser.add_argument("compute", action='append', type=str)
config_parser.add_argument("monitoring", action='append', type=str)


@config_blueprint.route('/', methods=['GET', 'POST'])
def config_list():
    if request.method == 'POST':
        args = config_parser.parse_args()
        # TODO check if config not valid
        # if not config_is_valid(args, cloud_info):
        #    return "try -d control=96 -d compute=98 -d compute=99 -X POST -v"
        response = Deployment.reserve_new_deployment(args)
        if not response:
            return "Deployment was not reserved"
        json_response = {"status": "config_created",
                         "deploy_id": response.id,
                         "config_url": f"{request.url}{response.id}/"}
        return jsonify(json_response)
    if request.method == 'GET':
        return {'config_list': [configuraiton.to_json() for configuraiton in Deployment.load_all()]}


@config_blueprint.route('/new')
def new_config():
    return render_template('new_config.html', nodes = Node.query.all())


@config_blueprint.route('/<int:config_id>/', methods=['GET', 'DELETE'])
def config(config_id):
    if request.method == 'GET':
        # TODO
        # abort_if_config_doesnt_exist(config_id)
        config_loaded = Deployment.load(config_id)
        if config_loaded is None:
            return f"Deployment {config_id} not found"
        return render_template('config.html', config=config_loaded)
    if request.method == 'DELETE':
        # TODO
        # abort_if_config_doesnt_exist(config_id)
        config_loaded = Deployment.load(config_id)
        if not config_loaded:
            return f"Deployment {config_id} not found"
        cloud_request = RequestExecutor(deploy_id=config_id,
                                        request_type=RequestExecutor.RequestType.REQUEST_DESTROY)
        app.get_request_manager().request_action(cloud_request)
        return f'Deployment {config_id} is scheduled to be destroyed', 204


@config_blueprint.route('/<int:config_id>/destroy')
def destroy(config_id):
    conf = Deployment.load(config_id)
    result = conf.request_destroy()
    return result

@config_blueprint.route('/<int:deploy_id>/delete')
def delete_deployment(deploy_id):
    conf = Deployment.load(deploy_id)
    result = conf.request_delete()
    return redirect('/')

@config_blueprint.route('/<int:config_id>/redeploy')
def redeploy(config_id):
    conf = Deployment.load(config_id)
    result = conf.request_redeploy()
    return result

@config_blueprint.route('/<int:config_id>/clean')
def clean_openstack(config_id):
    conf = Deployment.load(config_id)
    result = conf.request_clean()
    return result

@config_blueprint.route('/<int:config_id>/deploy')
def deploy(config_id):
    conf = Deployment.load(config_id)
    result = conf.request_deploy()
    return redirect(url_for('configs.config', config_id=config_id))


@config_blueprint.route('/<int:config_id>/rally_log')
def show_config_log(config_id):
    return send_from_directory(f"deploy_list/deploy{config_id}/", "log")


@config_blueprint.route('/<int:config_id>/run_rally_test')
def run_rally(config_id):
    # generate_rally_report(config_id)
    return \
        (url_for('rally_report', config_id=config_id))


@config_blueprint.route('/<int:config_id>/custom_load', methods=['POST'])
def custom_load(config_id):
    from openstack_tools import rally_manager
    load_code_file = rally_manager.prepare_custom_load(config_id, request.form['load_code'])
    request_kwargs = {'load_code_file': load_code_file}
    load_request = RequestExecutor(deploy_id=config_id,
                                   request_type=RequestExecutor.REQUEST_LOAD,
                                   request_kwargs = json.dumps(request_kwargs))
    app.get_request_manager().request_action(load_request)
    return redirect(url_for('configs.config', config_id=config_id))


@config_blueprint.route('/<int:config_id>/request_experiment', methods=['POST'])
def request_experiment(config_id):
    load_request = RequestExecutor(deploy_id=config_id,
                                   request_type=RequestExecutor.REQUEST_LOAD,
                                   request_kwargs = json.dumps(request.form))
    app.get_request_manager().request_action(load_request)
    return redirect(url_for('configs.config', config_id=config_id))

@config_blueprint.route('/<int:config_id>/requests/experiment/<int:request_id>/')
def experiment_results(config_id, request_id):
    from openstack_tools import rally_manager
    request = RequestExecutor.query.filter(RequestExecutor.id==request_id).first()
    return render_template('experiment_results.html',
                            results=rally_manager.get_experiment_results(config_id, request.get_task_name()))

@config_blueprint.route('/<int:deploy_id>/requests/experiment/<int:request_id>/repeat')
def repeat_experiment(deploy_id, request_id):
    request : RequestExecutor = RequestExecutor.query.filter(RequestExecutor.id==request_id).first()
    return render_template('new_experiment.html', deploy_id = deploy_id, kwargs = json.dumps(request.get_kwargs_dictionary()))


@config_blueprint.route('/<int:config_id>/requests/experiment/<int:request_id>/<load_id>/report_html')
def rally_report_html(config_id, request_id, load_id):
    request = RequestExecutor.query.filter(RequestExecutor.id==request_id).first()
    from openstack_tools import rally_manager
    file = rally_manager.get_html_report_file(config_id, request.get_task_name(), load_id)
    return send_file(file)


@config_blueprint.route('/<int:config_id>/requests/experiment/<int:request_id>/<load_id>/report_json')
def rally_json(config_id, request_id, load_id):
    request = RequestExecutor.query.filter(RequestExecutor.id==request_id).first()
    from openstack_tools import rally_manager
    file = rally_manager.get_json_report_file(config_id, request.get_task_name(), load_id)
    return send_file(file)


@config_blueprint.route('/<int:config_id>/requests/experiment/<int:request_id>/<load_id>/log')
def rally_log(config_id, request_id, load_id):
    request = RequestExecutor.query.filter(RequestExecutor.id==request_id).first()
    from openstack_tools import rally_manager
    file = rally_manager.get_log_file(config_id, request.get_task_name(), load_id)
    return send_file(file, mimetype='text/plain')

@config_blueprint.route('/<int:config_id>/requests/experiment/<int:request_id>/<load_id>/error')
def rally_error(config_id, request_id, load_id):
    request = RequestExecutor.query.filter(RequestExecutor.id==request_id).first()
    from openstack_tools import rally_manager
    file = rally_manager.get_error_file(config_id, request.get_task_name(), load_id)
    return send_file(file, mimetype='text/plain')

@config_blueprint.route('/<int:deployment_id>/requests/experiment/<int:request_id>/<load_id>/traces/<trace_file_id>')
def show_traces_html(deployment_id, request_id, load_id, trace_file_id):
    request = RequestExecutor.query.filter(RequestExecutor.id == request_id).first()
    from openstack_tools import rally_manager
    file = rally_manager.get_traces_html_file(deployment_id, request.get_task_name(), load_id, trace_file_id)
    return send_file(file)

@config_blueprint.route('/<int:config_id>/requests/experiment/<int:request_id>/full_dump')
def get_full_dump(config_id, request_id):
    request = RequestExecutor.query.filter(RequestExecutor.id == request_id).first()
    from openstack_tools import rally_manager
    return send_file(rally_manager.get_full_dump_file(config_id, request.get_task_name()+'.zip'))

@config_blueprint.route('/<int:config_id>/requests/experiment/<int:request_id>/html_report')
def get_full_html_report(config_id, request_id):
    request = RequestExecutor.query.filter(RequestExecutor.id == request_id).first()
    from openstack_tools import rally_manager
    file = rally_manager.get_full_html_report_file(config_id, request.get_task_name())
    return send_file(file)

@config_blueprint.route('/<int:config_id>/admin_openrc')
def get_admin_openrc(config_id):
    with open(f"{DEPLOY_FOLDER_LSTRIP}{config_id}/admin-openrc.sh", "r") as f:
        content = f.read()
    return Response(content, mimetype='text/plain')


@config_blueprint.route('/<int:config_id>/run_experiment')
def run_experiment(config_id):
    return render_template('new_experiment.html', deploy_id = config_id)

@config_blueprint.route('/<int:config_id>/requests/deploy_log')
def deploy_log(config_id):
    from openstack_tools import openstack_manager
    file = openstack_manager.get_deploy_log(config_id)
    return send_file(file, mimetype='text/plain')


@config_blueprint.route('/<int:config_id>/test')
def test(config_id):
    test_request = RequestExecutor(deploy_id=config_id,
                                   request_type= RequestExecutor.REQUEST_TEST)
    app.get_request_manager().request_action(test_request)
    return "10 sec pause scheduled"


@config_blueprint.route('/<int:config_id>/requests/<int:request_id>')
def get_request(config_id, request_id):
    request_loaded = app.get_request_manager().get_request(config_id, request_id)
    if request_loaded is None:
        return f"Request {request_id} for config {config_id} not found"
    return request_loaded.to_string()


@config_blueprint.route('/<int:config_id>/requests/<int:request_id>/cancel')
def cancel_request(config_id, request_id):
    app.get_request_manager().cancel_request(config_id, request_id)
    return redirect(url_for('configs.config', config_id=config_id))

@config_blueprint.route('/<int:deploy_id>/requests/')
def request_list(deploy_id):
    requests = RequestExecutor.query.filter(RequestExecutor.deploy_id==deploy_id).all()
    return render_template('request_list.html', request_list=requests, deploy_id=deploy_id)

@config_blueprint.route('/<int:config_id>/node/<string:node_name>/restart')
def restart_node(config_id, node_name):
    request_kwargs = {'node': node_name}
    test_request = RequestExecutor(deploy_id=config_id,
                                   request_type= RequestExecutor.REQUEST_NODE_RESTART,
                                   request_kwargs = json.dumps(request_kwargs))
    app.get_request_manager().request_action(test_request)
    return f"Restarting {node_name}"
