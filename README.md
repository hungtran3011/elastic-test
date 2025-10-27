# Elasticsearch on Google Cloud Deployment

This project deploys a custom Elasticsearch instance with Vietnamese text analysis to Google Kubernetes Engine (GKE).

## Architecture

- **Custom Elasticsearch**: Built with ICU analysis plugin for Vietnamese text processing
- **Kibana**: Web interface for Elasticsearch
- **Persistent Storage**: GKE persistent volumes for data persistence
- **Load Balancer**: External access to Kibana

## Quick Start

### 1. Prerequisites

- Google Cloud Project with billing enabled
- `gcloud` CLI installed and authenticated
- Docker installed locally
- kubectl installed

### 2. Initial Setup

Run the setup script to configure Google Cloud resources:

```bash
chmod +x setup-gcp.sh
./setup-gcp.sh YOUR_PROJECT_ID us-central1 elasticsearch-cluster
```

This will:

- Enable required APIs
- Create GKE cluster
- Set up service accounts and permissions
- Create Artifact Registry repository
- Configure Workload Identity for GitHub Actions

### 3. Local Testing

Test locally with Docker Compose:

```bash
docker-compose up --build
```

### 4. Deploy to Google Cloud

#### Option A: Using Cloud Build (Recommended)

Push to your GitHub repository and the Cloud Build trigger will automatically deploy:

```bash
git add .
git commit -m "Deploy to GKE"
git push origin main
```

#### Option B: Manual Cloud Build

```bash
gcloud builds submit --config cloudbuild.yaml \
  --substitutions _CLUSTER_NAME=elasticsearch-cluster,_REGION=us-central1 .
```

#### Option C: Using GitHub Actions

1. Add repository secrets:
   - `GCP_PROJECT_ID`: Your Google Cloud project ID
   - `GCP_WORKLOAD_IDENTITY_PROVIDER`: Workload identity provider path
   - `GCP_SERVICE_ACCOUNT`: Service account email

2. Push to trigger deployment or use workflow dispatch

### 5. Access Your Services

Get the external IP addresses:

```bash
# Get Kibana external IP
kubectl get services kibana-service

# Get cluster credentials
gcloud container clusters get-credentials elasticsearch-cluster --region=us-central1
```

- **Kibana**: `http://EXTERNAL_IP:5601`
- **Elasticsearch**: `http://elasticsearch-service:9200` (internal only)

## File Structure

```text
├── custom-elastic/
│   └── Dockerfile              # Custom Elasticsearch with ICU plugin
├── k8s-manifests.yaml          # Kubernetes deployment manifests
├── cloudbuild.yaml             # Cloud Build configuration
├── setup-gcp.sh               # Google Cloud setup script
├── .github/workflows/
│   └── deploy-gke.yml         # GitHub Actions workflow
├── docker-compose.yml          # Local development setup
└── main.py                     # Python application code
```

## Configuration

### Environment Variables

- `PROJECT_ID`: Your Google Cloud project ID
- `REGION`: GKE cluster region (default: us-central1)
- `CLUSTER_NAME`: GKE cluster name (default: elasticsearch-cluster)

### Elasticsearch Settings

- Single-node configuration
- ICU analysis plugin for Vietnamese text
- 1GB heap memory (configurable)
- Persistent storage: 10GB

## Troubleshooting

### Common Issues

1. **Build fails**: Check Docker image build logs
2. **Deployment fails**: Check GKE cluster status and permissions
3. **Services not accessible**: Verify firewall rules and load balancer status

### Logs

```bash
# View pod logs
kubectl logs -l app=elasticsearch
kubectl logs -l app=kibana

# View Cloud Build logs
gcloud builds list
gcloud builds log BUILD_ID
```

## Security Considerations

- Service account has minimal required permissions
- Workload Identity Federation for secure GitHub Actions
- No external Elasticsearch access (only internal)
- Kibana accessible via LoadBalancer

## Cost Optimization

- Use preemptible VMs for development clusters
- Scale down when not in use
- Monitor resource usage with Cloud Monitoring

## Cleanup

To delete all resources:

```bash
# Delete GKE cluster
gcloud container clusters delete elasticsearch-cluster --region=us-central1

# Delete Artifact Registry repository
gcloud artifacts repositories delete custom-elastic --location=us-central1

# Delete service account
gcloud iam service-accounts delete gke-deployer@YOUR_PROJECT_ID.iam.gserviceaccount.com
```