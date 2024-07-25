import os
import time
import datetime
import requests
import pandas as pd
import logging
from kubernetes import client, config
from dateutil import parser
from requests.auth import HTTPBasicAuth

# Configuration
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL")
NAMESPACE = os.getenv('NAMESPACE', 'otel-demo')
OUTPUT_FILE = os.getenv('OUTPUT_FILE', 'pod_metrics.csv')
SLEEP_INTERVAL = int(os.getenv('SLEEP_INTERVAL', 5))  # Time in seconds between data fetches

EXCLUDE_POD_NAMES = [
    "opensearch", "prometheus", "otelcol", "loadgenerator",
    "jaeger", "grafana", "featureflagservice"
]

# Azure AD Authentication details from environment variables
AZURE_AD_TENANT_ID = os.getenv("AZURE_AD_TENANT_ID")
AZURE_AD_CLIENT_ID = os.getenv("AZURE_AD_CLIENT_ID")
AZURE_AD_CLIENT_SECRET = os.getenv("AZURE_AD_CLIENT_SECRET")
AZURE_MONITOR_RESOURCE = "https://prometheus.monitor.azure.com"

# Logger setup
logging.basicConfig(filename='error.log', level=logging.ERROR)


def initialize_k8s_client():
    config.load_kube_config()
    return client.CoreV1Api()


def should_exclude_pod(pod_name):
    return any(excluded in pod_name for excluded in EXCLUDE_POD_NAMES)


def get_event_timestamp(event):
    if event.last_timestamp:
        return event.last_timestamp
    if event.event_time:
        return event.event_time
    return event.first_timestamp


def should_exclude_pod(pod_name):
    return any(excluded in pod_name for excluded in EXCLUDE_POD_NAMES)


def get_event_timestamp(event):
    if event.last_timestamp:
        return event.last_timestamp
    if event.event_time:
        return event.event_time
    return event.first_timestamp


def get_access_token():
    url = f"https://login.microsoftonline.com/{AZURE_AD_TENANT_ID}/oauth2/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": AZURE_AD_CLIENT_ID,
        "client_secret": AZURE_AD_CLIENT_SECRET,
        "resource": AZURE_MONITOR_RESOURCE
    }
    response = requests.post(url, data=data)
    response.raise_for_status()
    token_data = response.json()
    return token_data["access_token"]


def query_prometheus(query):
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{PROMETHEUS_URL}/api/v1/query"
    params = {"query": query}
    try:
        response = requests.post(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        return {item['metric']['pod']: float(item['value'][1]) for item in data['data']['result']}
    except requests.exceptions.RequestException as e:
        logging.error(f"An error occurred while querying Prometheus: {e}")
        return {}


def get_pod_status(v1, pod_name, namespace):
    try:
        pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        status = pod.status.phase
        reason = status if pod.status.reason is None else pod.status.reason
        restarts = sum(c.restart_count for c in (pod.status.container_statuses or []))
        ready_containers = sum(1 for c in (pod.status.container_statuses or []) if c.ready)
        total_containers = len(pod.spec.containers)
        return status, reason, restarts, ready_containers, total_containers, None
    except client.exceptions.ApiException as e:
        return 'NotFound' if e.status == 404 else 'Error', None, 0, 0, 0, str(e)
    except Exception as e:
        return 'Unknown', None, 0, 0, 0, str(e)


def get_pod_node_name(v1, pod_name, namespace):
    try:
        pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        return pod.spec.node_name
    except Exception as e:
        logging.error(f"Error getting node for pod {pod_name}: {e}")
        return 'Unknown'


def get_latest_pod_event(v1, pod_name, namespace):
    try:
        events = v1.list_namespaced_event(namespace, field_selector=f"involvedObject.name={pod_name}")
        valid_events = [event for event in events.items if event.last_timestamp]
        if valid_events:
            latest_event = sorted(valid_events, key=lambda x: x.last_timestamp, reverse=True)[0]
            event_age = datetime.datetime.now(datetime.timezone.utc) - latest_event.last_timestamp
            return {
                'Pod Event Type': latest_event.type,
                'Pod Event Reason': latest_event.reason,
                'Pod Event Age': str(event_age).split('.')[0],
                'Pod Event Source': latest_event.source.component,
                'Pod Event Message': latest_event.message
            }
        return {key: 'N/A' for key in
                ['Pod Event Type', 'Pod Event Reason', 'Pod Event Age', 'Pod Event Source', 'Pod Event Message']}
    except Exception as e:
        logging.error(f"Error getting events for pod {pod_name}: {e}")
        return {key: 'Unknown' for key in
                ['Pod Event Type', 'Pod Event Reason', 'Pod Event Age', 'Pod Event Source', 'Pod Event Message']}


def get_latest_event_details_node(v1, node_name):
    try:
        events = v1.list_event_for_all_namespaces(
            field_selector=f"involvedObject.kind=Node,involvedObject.name={node_name}")
        valid_events = [event for event in events.items if get_event_timestamp(event)]
        if valid_events:
            latest_event = sorted(valid_events, key=lambda x: get_event_timestamp(x), reverse=True)[0]
            event_timestamp = get_event_timestamp(latest_event)
            event_timestamp = parser.parse(event_timestamp) if isinstance(event_timestamp, str) else event_timestamp
            event_age = datetime.datetime.now(datetime.timezone.utc) - event_timestamp
            return {
                'Node Name': node_name,
                'Event Reason': latest_event.reason,
                'Event Age': str(event_age).split('.')[0],
                'Event Source': latest_event.source.component,
                'Event Message': latest_event.message
            }
        return {key: 'N/A' for key in ['Node Name', 'Event Reason', 'Event Age', 'Event Source', 'Event Message']}
    except Exception as e:
        logging.error(f"Error getting events for node {node_name}: {e}")
        return {key: 'Unknown' for key in ['Node Name', 'Event Reason', 'Event Age', 'Event Source', 'Event Message']}


def collect_pod_metrics(v1):
    print(f"Fetching data for pods in namespace {NAMESPACE}")

    current_pods = v1.list_namespaced_pod(namespace=NAMESPACE)
    current_pod_states = {pod.metadata.name: pod.status.phase for pod in current_pods.items if
                          not should_exclude_pod(pod.metadata.name)}

    cpu_usage_query = f"100 * max(rate(container_cpu_usage_seconds_total{{namespace=\"{NAMESPACE}\"}}[5m])) by (pod)"
    memory_usage_query = f"container_memory_working_set_bytes{{namespace=\"{NAMESPACE}\"}} / 1024 / 1024"
    memory_limit_query = f"kube_pod_container_resource_limits{{resource=\"memory\", namespace=\"{NAMESPACE}\"}} / 1024 / 1024"

    cpu_usage_data = query_prometheus(cpu_usage_query)
    memory_usage_data = query_prometheus(memory_usage_query)
    memory_limit_data = query_prometheus(memory_limit_query)

    data = []
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for pod in set(memory_usage_data.keys()).union(memory_limit_data.keys()):
        if should_exclude_pod(pod):
            continue
        memory_usage_percentage = (memory_usage_data.get(pod, 0) / memory_limit_data.get(pod,
                                                                                         0)) * 100 if memory_limit_data.get(
            pod, 0) > 0 else 'N/A'
        status, reason, restarts, ready_containers, total_containers, error_message = get_pod_status(v1, pod, NAMESPACE)
        latest_pod_event_details = get_latest_pod_event(v1, pod, NAMESPACE)
        node_name = get_pod_node_name(v1, pod, NAMESPACE)
        latest_event_node_details = get_latest_event_details_node(v1, node_name)
        data.append({
            'Timestamp': timestamp,
            'Pod Name': pod,
            'CPU Usage (%)': cpu_usage_data.get(pod, 'N/A'),
            'Memory Usage (%)': memory_usage_percentage,
            'Pod Status': status,
            'Pod Reason': reason,
            'Pod Restarts': restarts,
            'Ready Containers': ready_containers,
            'Total Containers': total_containers,
            'Error Message': error_message,
            **latest_pod_event_details,
            **latest_event_node_details,
        })

    return data


def write_to_csv(data):
    df = pd.DataFrame(data)
    write_header = not os.path.isfile(OUTPUT_FILE)
    df.to_csv(OUTPUT_FILE, index=False, mode='a', header=write_header)
    print(f"Data written to {OUTPUT_FILE}")


def main():
    v1 = initialize_k8s_client()
    last_known_pod_states = {}

    while True:
        try:
            data = collect_pod_metrics(v1)
            write_to_csv(data)
            time.sleep(SLEEP_INTERVAL)
        except KeyboardInterrupt:
            print("Script interrupted, exiting.")
            break
        except Exception as e:
            logging.error(f"An error occurred: {e}")


if __name__ == "__main__":
    main()
