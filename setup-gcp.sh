#!/bin/bash

# Google Cloud Setup Script for Elasticsearch Deployment
# This script sets up the necessary Google Cloud resources and permissions

set -e

# Configuration - Update these values
PROJECT_ID=${1:-"your-project-id"}
REGION=${2:-"us-central1"}
CLUSTER_NAME=${3:-"elasticsearch-cluster"}
SERVICE_ACCOUNT_NAME="gke-deployer"

echo "🚀 Setting up Google Cloud for Elasticsearch deployment..."
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Cluster: $CLUSTER_NAME"

# Authenticate
echo "📋 Authenticating to Google Cloud..."
gcloud auth login
gcloud config set project $PROJECT_ID

# Enable required APIs
echo "🔧 Enabling required APIs..."
gcloud services enable container.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable artifactregistry.googleapis.com
gcloud services enable iamcredentials.googleapis.com

# Create service account
echo "👤 Creating service account..."
gcloud iam service-accounts create $SERVICE_ACCOUNT_NAME \
  --description="Service account for GKE deployments" \
  --display-name="GKE Deployer"

SERVICE_ACCOUNT_EMAIL="$SERVICE_ACCOUNT_NAME@$PROJECT_ID.iam.gserviceaccount.com"

# Grant permissions
echo "🔑 Granting permissions..."
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
  --role="roles/container.developer"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
  --role="roles/storage.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
  --role="roles/artifactregistry.writer"

# Create GKE cluster
echo "🏗️ Creating GKE cluster..."
gcloud container clusters create $CLUSTER_NAME \
  --region=$REGION \
  --num-nodes=2 \
  --machine-type=e2-medium \
  --disk-size=50GB \
  --enable-ip-alias \
  --enable-workload-identity

# Create Artifact Registry repository
echo "📦 Creating Artifact Registry repository..."
gcloud artifacts repositories create custom-elastic \
  --repository-format=docker \
  --location=$REGION \
  --description="Docker repository for custom Elasticsearch images"

# Setup Workload Identity for GitHub Actions (optional)
echo "🔗 Setting up Workload Identity for GitHub Actions..."
WORKLOAD_IDENTITY_POOL="github-pool"
WORKLOAD_IDENTITY_PROVIDER="github-provider"

gcloud iam workload-identity-pools create $WORKLOAD_IDENTITY_POOL \
  --location="global" \
  --description="Workload Identity Pool for GitHub Actions"

gcloud iam workload-identity-pools providers create-oidc $WORKLOAD_IDENTITY_PROVIDER \
  --location="global" \
  --workload-identity-pool=$WORKLOAD_IDENTITY_POOL \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository" \
  --issuer-uri="https://token.actions.githubusercontent.com"

# Allow service account to be impersonated
gcloud iam service-accounts add-iam-policy-binding $SERVICE_ACCOUNT_EMAIL \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')/locations/global/workloadIdentityPools/$WORKLOAD_IDENTITY_POOL/attribute.repository/hungtran3011/elastic-test"

# Create Cloud Build trigger (optional)
echo "🏗️ Creating Cloud Build trigger..."
gcloud builds triggers create github \
  --name="deploy-elasticsearch" \
  --repository="projects/$PROJECT_ID/locations/$REGION/connections/github-connection/repositories/elastic-test" \
  --branch-pattern="^main$" \
  --build-config="cloudbuild.yaml" \
  --region=$REGION

echo "✅ Setup completed!"
echo ""
echo "📝 Next steps:"
echo "1. For GitHub Actions:"
echo "   - Add these secrets to your GitHub repository:"
echo "     * GCP_PROJECT_ID: $PROJECT_ID"
echo "     * GCP_WORKLOAD_IDENTITY_PROVIDER: projects/$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')/locations/global/workloadIdentityPools/$WORKLOAD_IDENTITY_POOL/providers/$WORKLOAD_IDENTITY_PROVIDER"
echo "     * GCP_SERVICE_ACCOUNT: $SERVICE_ACCOUNT_EMAIL"
echo ""
echo "2. For Cloud Build:"
echo "   - The trigger has been created and will deploy on pushes to main branch"
echo ""
echo "3. Test the deployment:"
echo "   - Push changes to your main branch"
echo "   - Or run: gcloud builds submit --config cloudbuild.yaml --substitutions _CLUSTER_NAME=$CLUSTER_NAME,_REGION=$REGION ."
echo ""
echo "4. Access your services:"
echo "   - Elasticsearch: kubectl get services elasticsearch-service"
echo "   - Kibana: kubectl get services kibana-service"