import json
import logging
import os
from shutil import copyfile

from flask import Flask, render_template, request, redirect
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import SQLAlchemyError

NODE_LIST = 'node_list'

def prepare_environment():
    rally_home_directory = os.path.expanduser('~/.rally')
    if not os.path.exists(rally_home_directory + "/plugins"):
        os.makedirs(rally_home_directory + "/plugins")
    copyfile("./rally_files/complete_test_run.py", rally_home_directory + "/plugins/complete_test_run.py")
    print("flask environment prepared")


logging.getLogger().setLevel(logging.INFO)


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

from routing.config_routes import config_blueprint
from cloud_components.request_manager import RequestManager

request_manager = RequestManager()

from models.deployment import Deployment
from models.node import Node

def ensure_tables():
    db.create_all()
    if Node.query.first():
        return
    try:
        with open('node_list') as json_file:
            data = json.load(json_file)
            for node in data['node_list']:
                new_node = Node(name=node['name'], domain=node['domain_name'], ip=node['ip'])
                db.session.add(new_node)
            db.session.commit()
            if 'deployment_list' in data:
                for deployment in data['deployment_list']:
                    new_deployment: Deployment = Deployment(id = int(deployment['id']))
                    control_node: Node = Node.query.filter(Node.name == deployment['control']).first()
                    control_node.control = True
                    new_deployment.nodes.append(control_node)
                    monitoring_node: Node = Node.query.filter(Node.name == deployment['monitoring']).first()
                    monitoring_node.monitoring = True
                    new_deployment.nodes.append(control_node)
                    for compute_node_name in deployment['compute']:
                        compute_node = Node.query.filter(Node.name == compute_node_name).first()
                        compute_node.compute = True
                        if not compute_node == control_node:
                            new_deployment.nodes.append(compute_node)
                    new_deployment.state = deployment['state']
                    db.session.add(new_deployment)
            db.session.commit()

    except SQLAlchemyError as e:
        app.logger.error(e)
        db.session.rollback()
    db.session.commit()

ensure_tables()

prepare_environment()
from openstack_tools.rally_manager import init_rally

init_rally()

def get_request_manager():
    return request_manager


def get_db():
    return db


@app.route('/')
def index():
    return render_template('index.html', config_list=Deployment.load_all())


def to_json(obj):
    def dumper(obj):
        try:
            return json.dumps(obj)
        except:
            to_json_internal_method = getattr(obj, "to_json", None)
            if callable(to_json_internal_method):
                return to_json_internal_method(obj)
            return obj.__dict__

    return json.dumps(obj, default=dumper)



@app.route('/compress/<request_id>/')
def compress(request_id):
    from cloud_components.request_executor import RequestExecutor
    re: RequestExecutor = RequestExecutor.query.filter(RequestExecutor.id==request_id).first()
    from openstack_tools import rally_manager
    rally_manager.compress_output_data(re.deploy_id, re.get_task_name())
    from datetime import datetime
    re.request_end = datetime.now()
    re.save()
    return "finilazed"

@app.route('/drop')
def drop_tables():
    db.drop_all()
    ensure_tables()
    return "drop tables initiated"

@app.route('/metrics')
def metrics():
    from openstack_tools import metrics_collector
    deployment_id = 1
    from datetime import datetime
    format = "YYYY-MM-DD HH:MM:SS.mmmmmm"
    start = datetime.fromisoformat("2021-07-19 10:00:00.000000")
    end   = datetime.fromisoformat("2021-07-19 10:20:00.400000")
    from openstack_tools.metrics_collector import MetricsCollector
    mc = MetricsCollector(1, "task_2021.07.06_16:59:52", "load0", start, end)
    mc.extract_metrics()
    return "debugging"

@app.route('/prepare')
def prepare():
    deployment_id = 1
    from openstack_tools import openstack_manager
    result = openstack_manager.prepare_openstack(deployment_id)
    result = result + openstack_manager.prepare_elasticsearch(deployment_id)
    return 'done'

@app.route('/bootstrap')
def bootstrap():
    deployment_id = 1
    from openstack_tools import openstack_manager
    openstack_manager.bootstrap_deployment(deployment_id)
    return 'done'

@app.route('/request_experiment', methods=['POST'])
def signup():
    email = request.form['email']
    print("The email address is '" + email + "'")
    return redirect('/')

app.register_blueprint(config_blueprint)




