#!/bin/bash

# Load environment variables from config.env
if [ -f ./config.env ]; then
  export $(grep -v '^#' ./config.env | xargs)
else
  echo "Error: config.env file not found!"
  exit 1
fi

echo "Using parameters:"
echo "REGION=$REGION"
echo "SNS_ACCOUNT_ID=$SNS_ACCOUNT_ID"
echo "SNS_ENDPOINT=$SNS_ENDPOINT"
echo "PREFIX=$PREFIX"

## Create EKS
eksctl create cluster -f eks-config.yaml 
aws eks update-kubeconfig --region "$REGION" --name video-knative

## Config EKS
kubectl apply -f https://github.com/knative/serving/releases/download/knative-v1.14.0/serving-crds.yaml
kubectl apply -f https://github.com/knative/serving/releases/download/knative-v1.14.0/serving-core.yaml
kubectl apply -f https://github.com/knative/net-kourier/releases/download/knative-v1.14.0/kourier.yaml
kubectl patch configmap/config-network -n knative-serving -p '{"data":{"ingress.class":"kourier.ingress.networking.knative.dev"}}'

## Create ECR
aws ecr create-repository --repository-name default/knative-video --image-scanning-configuration scanOnPush=true --region "$REGION" --tags Key=CreatedBy,Value=CLI
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$SNS_ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"

## Create SNS topic
SNS_TOPIC_ARN="arn:aws:sns:$REGION:$SNS_ACCOUNT_ID:video-topic"
aws sns create-topic --name video-topic --region "$REGION"

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

## Create S3 bucket
aws s3api create-bucket --bucket knative-video-s3 --region "$REGION"

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
                \"Value\": \"$PREFIX-\"
              }
            ]
          }
        }
      }
    ]
  }"

SNS_ENDPOINT="http://$(kubectl get svc nginx-proxy -n default -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')/sns"
## Set HTTP notifications
aws sns subscribe \
  --topic-arn "$SNS_TOPIC_ARN" \
  --protocol http \
  --notification-endpoint "$SNS_ENDPOINT"

cd ./main
func deploy --build --repository 125383788004.dkr.ecr.us-east-1.amazonaws.com/default/knative-video:main
cd ../

## Deploy nGINX
kubectl apply -f nginx-config.yaml
kubectl apply -f nginx-proxy.yaml
