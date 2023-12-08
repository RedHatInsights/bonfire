import logging
import requests
from concurrent.futures import ThreadPoolExecutor

import bonfire.config as conf


log = logging.getLogger(__name__)


class AsyncElasticsearchHandler(logging.Handler):
    def __init__(self, es_url):
        super().__init__()
        self.es_url = es_url
        self.executor = ThreadPoolExecutor(max_workers=10)

    def emit(self, record):
        log_entry = self.format(record)
        if conf.ENABLE_TELEMETRY:
            self.executor.submit(self.send_to_es, log_entry)

    def send_to_es(self, log_entry):
        # Convert log_entry to JSON and send to Elasticsearch
        try:
            headers = {"Authorization": conf.ELASTICSEARCH_APIKEY,
                       "Content-Type": "application/json"}

            response = requests.post(self.es_url, headers=headers, data=log_entry, timeout=0.1)
            response.raise_for_status()
        except Exception as e:
            # Handle exceptions (e.g., network issues, Elasticsearch down)
            log.error("Error sending data to elasticsearch: %s", e)
