from flask import Flask, request
from bonfire import namespaces

import json

app = Flask(__name__)


@app.route("/")
def welcome():
    return "Welcome to the bonfire api"


@app.route("/namespaces")
def get_namespaces():
    ns_list = namespaces.get_namespaces()
    data = {'namespaces': []}
    for ns in ns_list:
        data['namespaces'].append({
            "name": ns.name,
            "reserved": ns.reserved,
            "status": ns.status,
            "apps": ns.clowdapps,
            "requester": ns.requester,
            "expires_in": ns.expires_in,
        })
    return json.dumps(data), 200


@app.route("/namespaces", methods=["POST"])
def reserve_namespace():
    res_info = request.get_json()

    name = None
    requester = None
    duration = '1h'
    timeout = 600

    if res_info:
        if 'name' in res_info:
            name = res_info['name']
        if 'requester' in res_info:
            requester = res_info['requester']
        if 'duration' in res_info:
            duration = res_info['duration']
        if 'timeout' in res_info:
            timeout = res_info['timeout']
    
    ns = namespaces.reserve_namespace(name, requester, duration, timeout)

    data = {
        'namespace': ns.name,
    }

    return json.dumps(data), 201


@app.route("/namespaces/<ns_name>", methods=["PUT"])
def extend_namespace(ns_name):
    duration = '1h'
    namespaces.extend_namespace(ns_name, duration)
    
    return "", 204


@app.route("/namespaces/<ns_name>", methods=["DELETE"])
def release_namespace(ns_name):
    namespaces.release_namespace(ns_name)

    return "", 204
