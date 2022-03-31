import json
import logging
from datetime import datetime
from time import sleep

import app
import utils
from app import db

FOLDER_REQUEST_HISTORY = "request_history/"


class RequestExecutor (db.Model):

    id = db.Column(db.Integer, primary_key=True)
    deploy_id = db.Column(db.Integer, db.ForeignKey('deployment.id'), nullable=False)
    request_time = db.Column(db.DateTime, default=datetime.now)
    request_type = db.Column(db.String)
    request_start = db.Column(db.DateTime)
    request_end = db.Column(db.DateTime)
    request_kwargs = db.Column(db.String)

    def __init__(self, **kwargs):
        super(RequestExecutor, self).__init__(**kwargs)

    REQUEST_RESERVE = "request_reserve"
    REQUEST_DEPLOY = "request_deploy"
    REQUEST_DESTROY = "request_destroy"
    REQUEST_DELETE = "request_delete"
    REQUEST_REDEPLOY = "request_redeploy"
    REQUEST_LOAD = "request_load"
    REQUEST_TEST = "request_test"
    REQUEST_CLEAN = "request_clean"
    REQUEST_NODE_RESTART = "request_node_restart"

    def execute(self):
        logging.info(f'Deploy {self.deploy_id} executing request {self.request_type}')
        self.request_start = datetime.now()
        self.save()
        self.executors_mapping[self.request_type](self)
        self.request_end = datetime.now()
        self.save()
        logging.info(f'Config {self.deploy_id} execution of {self.request_type} finished')

    def get_id(self):
        return self.id

    def is_done(self):
        return self.request_end != None

    def get_task_name(self):
        return self.request_start.strftime(utils.TIME_TO_TASK_NAME)

    def to_string(self):
        return json.dumps(
            {'id': self.id,
             'deploy_id': self.deploy_id,
             'request_type': self.request_type,
             'request_kwargs': self.request_kwargs,
             'request_time': self.request_time.strftime(utils.DATETIME_FORMAT) if self.request_time else "None",
             'request_start': self.request_start.strftime(utils.DATETIME_FORMAT) if self.request_start else "None",
             'request_end': self.request_end.strftime(utils.DATETIME_FORMAT) if self.request_end else "None"}
        )

    def __prepare_config__(self):
        from openstack_tools import openstack_manager
        openstack_manager.prepare_config_files(self.deploy_id)

    def __deploy__(self):
        from openstack_tools import openstack_manager
        openstack_manager.deploy_config(self.deploy_id)

    def __destroy__(self):
        from openstack_tools import openstack_manager
        openstack_manager.destroy_config(self.deploy_id)

    def __delete__(self):
        from openstack_tools import openstack_manager
        openstack_manager.delete_deployment(self.deploy_id)

    def __redeploy__(self):
        from openstack_tools import openstack_manager
        openstack_manager.redeploy_config(self.deploy_id)

    def __clean_openstack__(self):
        from openstack_tools import openstack_manager
        openstack_manager.clear_openstack(self.deploy_id)

    def __generate_load__(self):
        kwargs = self.get_kwargs_dictionary()
        from openstack_tools.experiment_manager import ExperimentManager
        experiment = ExperimentManager(self.deploy_id, self.get_task_name(), kwargs)
        experiment.execute()

    def __node_restart__(self):
        kwargs = self.get_kwargs_dictionary()
        from openstack_tools import openstack_manager
        openstack_manager.node_restart(self.deploy_id, kwargs)

    def get_kwargs_dictionary(self):
        return json.loads(self.request_kwargs)

    def __test__(self):
        sleep(10)

    executors_mapping = {
        REQUEST_RESERVE: __prepare_config__,
        REQUEST_DEPLOY: __deploy__,
        REQUEST_DESTROY: __destroy__,
        REQUEST_DELETE: __delete__,
        REQUEST_REDEPLOY: __redeploy__,
        REQUEST_LOAD: __generate_load__,
        REQUEST_TEST: __test__,
        REQUEST_CLEAN: __clean_openstack__,
        REQUEST_NODE_RESTART: __node_restart__
    }

    def save(self):
        app.get_db().session.commit()
