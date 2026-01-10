# Elasticsearch on Google Cloud Deployment

This project deploys a custom Elasticsearch instance with Vietnamese text analysis to Google Kubernetes Engine (GKE).

## Architecture

- **Custom Elasticsearch**: Built with ICU analysis plugin for Vietnamese text processing
- **Kibana**: Web interface for Elasticsearch
- **Persistent Storage**: GKE persistent volumes for data persistence
- **Load Balancer**: External access to Kibana

## Quick Start

### Run the full app (Windows / PowerShell)

- Starts/uses local venv in `.venv`
- Installs Python deps from `requirement.txt`
- Starts Elasticsearch + Kibana via `docker-compose.yml`
- Runs the FastAPI web facade (with background sync scheduler)

```powershell
./start.ps1
```

Optional:

```powershell
./start.ps1 -SkipDocker
./start.ps1 -Port 8001
```

### Run crawler as a separate process

If you want crawling to run independently from the web server (recommended for production-like setup):

1) Disable the web app scheduler via `.env`:

```env
ENABLE_WEB_SCHEDULER=false
SCRAPE_INTERVAL_MINUTES=60
```

1) Run the crawler service:

```powershell
./start-crawler.ps1
```

1) Run the web app:

```powershell
./start.ps1 -SkipDocker
```

### One-time manual sync

```powershell
./sync.ps1
```

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

## Crawler — local quick run

Follow these steps to run the crawler locally and import sample data to Supabase (Windows / PowerShell).

1) Create & activate virtualenv:

```powershell
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
```

2) Upgrade packaging tools and install requirements:

```powershell
python -m pip install --upgrade pip setuptools wheel
pip install -r requirement.txt
# Optional useful packages for Supabase import
pip install supabase python-dotenv
```

3) (Optional) Create a `.env` in project root with your Supabase credentials:

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key
```

4) Run the scraper for a single category (example: `trinh-tham`, 4 listing pages, up to 200 chapters per story):

```powershell
python scraper.py --category trinh-tham --max-pages 4 --chapters 200 --delay 0.2 --resume --job-id trinh-tham
```

5) Import the crawled JSON files for a category into Supabase (uploads stories and chapters):

```powershell
python import-to-supabase.py data/ngon-tinh
```

Notes:
- Use the Service Role key from Supabase for write/upsert operations (Settings → API → Service Role).  
- If you only want to demo a single category, point the import script at that category folder (e.g. `data/kiem-hiep`).  
- Make sure `.env` is NOT committed to git (add `.env` to `.gitignore`).