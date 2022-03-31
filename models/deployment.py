import json
import logging
import os

import app
import utils
from app import db
from cloud_components.request_executor import RequestExecutor
from utils import DEPLOY_FOLDER_LSTRIP
from models.node import Node


class Deployment(db.Model):
    STATE_PLANNED = "planned"
    STATE_DEPLOYED = "deployed"
    STATE_DESTROYED = "destroyed"

    RALLY_REPORT_JSON = "rally_report.json"
    RALLY_REPORT_HTML = "rally_report.html"
    LOG_DUMP = "log_dump.json"

    OUTPUT_FOLDER = "output/"
    HTML_OUTPUT_FOLDER = "html_reports/"

    LOG_GENERAL = "log.general"
    LOG_DEPLOYER = "log.deployer"
    LOG_RALLY = "log.rally"

    id = db.Column(db.Integer, primary_key=True)
    nodes = db.relationship('Node', lazy=True)
    state = db.Column(db.String, default=STATE_PLANNED)

    def get_control_node(self) -> Node:
        return next(iter([node for node in self.nodes if node.control is True] or []), None)

    def get_monitoring_node(self) -> Node:
        monitoring = next(iter([node for node in self.nodes if node.monitoring is True] or []), None)
        if not monitoring:
            return self.get_control_node()
        return monitoring

    def get_compute_nodes(self):
        return [node for node in self.nodes if node.compute is True]

    def to_json(self):
        return self.__dict__

    @staticmethod
    def from_json(json_data):
        new_info = Deployment()
        new_info.__dict__ = json_data
        return new_info

    def get_control_url(self):
        return self.get_control_node().domain

    def get_monitoring_url(self):
        return self.get_monitoring_node().domain

    def set_state(self, state):
        self.state = state
        return self

    def set_state_and_save(self, state):
        self.set_state(state)
        self.save()
        return self

    def is_planned(self):
        return self.state == Deployment.STATE_PLANNED

    def is_deployed(self):
        return self.state == Deployment.STATE_DEPLOYED

    def is_destroyed(self):
        return self.state == Deployment.STATE_DESTROYED

    def can_be_deleted(self):
        if self.is_destroyed() or self.is_planned():
            return True
        return False

    def get_log_file_path(self, log_type):
        if os.path.exists(f"{DEPLOY_FOLDER_LSTRIP}{self.id}/{log_type}"):
            return f"{DEPLOY_FOLDER_LSTRIP}{self.id}/log"
        else:
            return None

    def is_destroyable(self):
        if self.is_deployed():
            return True
        return False

    def request_destroy(self):
        if self.is_destroyable():
            destroy_request = RequestExecutor(deploy_id=self.id, request_type=RequestExecutor.REQUEST_DESTROY)
            app.get_request_manager().request_action(destroy_request)
            return f'Deployment {self.id} is scheduled to be destroyed'
        else:
            return f'Deployment {self.id} can not be destroyed'

    def request_experiment(self):
        load_request = RequestExecutor(deploy_id=self.id, request_type=RequestExecutor.REQUEST_LOAD)
        app.get_request_manager().request_action(load_request)
        return f'Experiment for {self.id} is scheduled'

    def is_redeployable(self):
        if self.is_deployed():
            return True
        return False

    def is_deployable(self):
        if not self.is_deployed():
            return True
        return False

    def request_deploy(self):
        if self.is_deployable():
            req_executor = RequestExecutor(deploy_id = self.id, request_type= RequestExecutor.REQUEST_DEPLOY)
            app.get_request_manager().request_action(req_executor)
            return f'Configuration {self.id} is scheduled to be deployed'
        else:
            return f'Configuration {self.id} can not be deployed'

    def request_delete(self):
        if not self.can_be_deleted():
            return
        request_delete = RequestExecutor(deploy_id = self.id, request_type = RequestExecutor.REQUEST_DELETE)
        app.get_request_manager().request_action(request_delete)

    def request_redeploy(self):
        req_executor = RequestExecutor(deploy_id = self.id, request_type = RequestExecutor.REQUEST_REDEPLOY)
        app.get_request_manager().request_action(req_executor)
        return f'Configuration {self.id} is scheduled to be redeployed'

    def request_clean(self):
        req_executor = RequestExecutor(deploy_id = self.id, request_type = RequestExecutor.REQUEST_CLEAN)
        app.get_request_manager().request_action(req_executor)
        return f'Configuration {self.id} is scheduled to be cleaned up'

    def get_scheduled_requests(self):
        result = app.get_request_manager().get_schedule(self.id)
        logging.info(result)
        return result

    def get_current_request(self):
        result = app.get_request_manager().get_current_request(self.id)
        logging.info(result)
        return result

    def get_connection_string(self):
        return "http://"+self.get_control_url()+":"+str(utils.PORT_ELASTICSEARCH)

    @staticmethod
    def load(deploy_id) -> 'Deployment':
        return Deployment.query.filter_by(id=deploy_id).first()

    @staticmethod
    def load_all():
        return Deployment.query.all()

    @staticmethod
    def reserve_new_deployment(args):
        if not args['compute'] or not args['control']:
            return None
        nodes = Node.query.filter(Node.name.in_(args['compute'] + args['control'] + args['monitoring'])).all()
        new_deployment = Deployment()
        if '-' in args['monitoring']:
            args['monitoring'] = args['control']
        for node in nodes:
            if node.deployment_id:
                ## f"{node.name} is already in use by deployment {node.deployment_id}"
                return None
            if node.name in args['compute']:
                node.compute = True
            if node.name in args['control']:
                node.control = True
            if node.name in args['monitoring']:
                node.monitoring = True
            new_deployment.nodes.append(node)
        db.session.add(new_deployment)
        db.session.commit()
        reserve_request = RequestExecutor(deploy_id=new_deployment.id,
                                          request_type=RequestExecutor.REQUEST_RESERVE)
        app.get_request_manager().request_action(reserve_request)
        return new_deployment