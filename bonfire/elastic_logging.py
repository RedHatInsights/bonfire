import logging
import json
import requests
import datetime
from concurrent.futures import ThreadPoolExecutor

import bonfire.config as conf

class AsyncElasticsearchHandler(logging.Handler):
    def __init__(self, es_url):
        super().__init__()
        self.es_url = es_url
        self.executor = ThreadPoolExecutor(max_workers=10)

    def emit(self, record):
        log_entry = self.format(record)
        self.executor.submit(self.send_to_es, log_entry)

    def send_to_es(self, log_entry):
        # Convert log_entry to JSON and send to Elasticsearch
        try:
            headers = {"Authorization": conf.ELASTICSEARCH_APIKEY,
                       "Content-Type": "application/json"}
            log = {"timestamp": datetime.datetime.now().isoformat(), "message": log_entry}
            response = requests.post(self.es_url, headers=headers, data=json.dumps(log), verify=False)
            response.raise_for_status()
        except Exception as e:
            # Handle exceptions (e.g., network issues, Elasticsearch down)
            print(f"ERROR: {response.status_code}")
