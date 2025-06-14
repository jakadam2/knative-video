#!/usr/bin/env bash

set -euo pipefail

# Load environment variables safely
set -o allexport
source ./config.env
set +o allexport

echo "REGION=$REGION"
echo "SNS_ACCOUNT_ID=$SNS_ACCOUNT_ID"
echo "PREFIX=$PREFIX"

## Create EKS
eksctl create cluster -f eks-config.yaml 
aws eks update-kubeconfig --region "$REGION" --name video-knative

## Config EKS
kubectl apply -f https://github.com/knative/serving/releases/download/knative-v1.14.0/serving-crds.yaml
kubectl apply -f https://github.com/knative/serving/releases/download/knative-v1.14.0/serving-core.yaml
kubectl apply -f https://github.com/knative/net-kourier/releases/download/knative-v1.14.0/kourier.yaml
kubectl patch configmap/config-network -n knative-serving -p '{"data":{"ingress.class":"kourier.ingress.networking.knative.dev"}}'

## Deploy nGINX
kubectl apply -f nginx-config.yaml
kubectl apply -f nginx-proxy.yaml
kubectl apply -f nginx-service.yaml

## Wait for proxy
sleep 120

## Create ECR
aws ecr create-repository \
  --repository-name default/knative-video \
  --image-scanning-configuration scanOnPush=true \
  --region "$REGION" \
  --tags Key=CreatedBy,Value=CLI

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$SNS_ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"

## Create SNS topic
SNS_TOPIC_ARN="arn:aws:sns:$REGION:$SNS_ACCOUNT_ID:video-topic"
aws sns create-topic --name video-topic --region "$REGION" >/dev/null

## Set SNS privileges
aws sns set-topic-attributes \
  --topic-arn "$SNS_TOPIC_ARN" \
  --attribute-name Policy \
  --attribute-value "{
    \"Version\": \"2008-10-17\",
    \"Id\": \"PublicAccessPolicy\",
    \"Statement\": [
      {
        \"Sid\": \"AllowAllPublish\",
        \"Effect\": \"Allow\",
        \"Principal\": \"*\",
        \"Action\": \"SNS:Publish\",
        \"Resource\": \"$SNS_TOPIC_ARN\"
      },
      {
        \"Sid\": \"AllowAllSubscribe\",
        \"Effect\": \"Allow\",
        \"Principal\": \"*\",
        \"Action\": \"SNS:Subscribe\",
        \"Resource\": \"$SNS_TOPIC_ARN\"
      }
    ]
  }" \
  --region "$REGION"

## Create S3 bucket (works differently in us-east-1!)
if [[ "$REGION" == "us-east-1" ]]; then
  aws s3api create-bucket --bucket knative-video-s3 --region "$REGION"
else
  aws s3api create-bucket --bucket knative-video-s3 \
    --region "$REGION" \
    --create-bucket-configuration LocationConstraint="$REGION"
fi

## Set notification policy with prefix filter
aws s3api put-bucket-notification-configuration \
  --bucket knative-video-s3 \
  --notification-configuration "{
    \"TopicConfigurations\": [
      {
        \"Id\": \"knative-video-notification\",
        \"TopicArn\": \"$SNS_TOPIC_ARN\",
        \"Events\": [\"s3:ObjectCreated:*\"],
        \"Filter\": {
          \"Key\": {
            \"FilterRules\": [
              {
                \"Name\": \"prefix\",
                \"Value\": \"__process__\"
              }
            ]
          }
        }
      }
    ]
  }"


# ## Set public bucket policy
# aws s3api put-bucket-policy \
#   --bucket knative-video-s3 \
#   --policy "{
#     \"Version\": \"2012-10-17\",
#     \"Statement\": [
#       {
#         \"Sid\": \"PublicReadWriteGetPut\",
#         \"Effect\": \"Allow\",
#         \"Principal\": \"*\",
#         \"Action\": [
#           \"s3:GetObject\",
#           \"s3:PutObject\"
#         ],
#         \"Resource\": \"arn:aws:s3:::knative-video-s3/*\"
#       }
#     ]
#   }"

## Deploy function
cd ./main
func deploy --build --image "$SNS_ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/default/knative-video:main"
cd ..

## Get SNS endpoint from nginx
SNS_ENDPOINT_HOST=$(kubectl get svc nginx-proxy --namespace default -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
SNS_ENDPOINT="http://$SNS_ENDPOINT_HOST/sns"
echo "SNS Endpoint: $SNS_ENDPOINT"

## Set HTTP notifications
aws sns subscribe \
  --topic-arn "$SNS_TOPIC_ARN" \
  --protocol http \
  --notification-endpoint "$SNS_ENDPOINT" \
  --region "$REGION"

echo "END"