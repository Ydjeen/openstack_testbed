from enum import Enum

from app import db


class Node(db.Model):

    STATE_ACTIVE = "active"
    STATE_RESTARTING = "restarting"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, unique=True)
    domain = db.Column(db.String)
    ip = db.Column(db.String)
    deployment_id = db.Column(db.Integer, db.ForeignKey('deployment.id'), nullable=True)
    control = db.Column(db.Boolean, default=False)
    monitoring = db.Column(db.Boolean, default=False)
    compute = db.Column(db.Boolean, default=False)
    state = db.Column(db.String, default=STATE_ACTIVE)

    def __init__(self, **kwargs):
        super(Node, self).__init__(**kwargs)

    @staticmethod
    def wally_to_ip(domain):
        return f'130.149.249.{int(domain[5:] + 10)}'
