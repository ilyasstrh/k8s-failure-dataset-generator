# Kubernetes Failure Dataset Generator

## Overview
The `k8s-failure-dataset-generator` is a Python script designed to collect and process Kubernetes (K8s) pod metrics to generate datasets. It utilizes Kubernetes API and Prometheus for real-time data collection while using Chaos Mesh for simulating various operational scenarios.

## Features
- Collects real-time metrics from Kubernetes pods.
- Generates datasets useful for anomaly detection and maintenance.

## Prerequisites
- Python 3.x
- Kubernetes cluster.
- Prometheus.
- Access to Kubernetes API.

## Installation
Clone the repository to your local machine:

```sh
git clone https://github.com/ilyasstrh/k8s-failure-dataset-generator.git
cd k8s-failure-dataset-generator
```


## Configuration
Edit the `dataset_generator.py` file to update the following settings as per your environment:
- `prometheus_url`: URL of your Prometheus instance.
- `namespace`: Kubernetes namespace to monitor.
- `output_file`: the exported CSV filename.
- `exclude_pod_names`: List of pod names to exclude from monitoring.
- `sleep_interval`: Interval (in seconds) between data fetches.

## Usage
Run the script using Python:

```sh
python3 dataset_generator.py
```


The script will start collecting data from the specified Kubernetes environment and save it to a CSV file at the configured intervals.

## Contributing
Contributions to `k8s-failure-dataset-generator` are welcome! Please follow the standard GitHub flow: fork the repo, make changes, and submit a pull request.

## License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgements
- OpenTelemetry for the demo application.

## Contact
Please, contact me for any queries or contributions.
