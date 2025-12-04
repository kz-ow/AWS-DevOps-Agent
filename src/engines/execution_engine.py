import boto3
import docker
import base64
import json
import time
from config import settings

class ExecutionEngine:
    def __init__(self):
        self.docker_client = docker.from_env()
        # AWS設定がある場合のみクライアント初期化
        if settings.HAS_AWS_CREDS:
            self.ecr = boto3.client('ecr', region_name=settings.AWS_REGION)
            self.lambda_client = boto3.client('lambda', region_name=settings.AWS_REGION)
            self.iam = boto3.client('iam')

    # --- Local Mode ---
    def deploy_to_local(self, build_dir: str, project_name: str) -> str:
        tag = f"{project_name}:local"
        container_name = f"{project_name}-dev"
        
        print(f"🏠 Local Build & Run: {tag}")
        self.docker_client.images.build(path=str(build_dir), tag=tag)
        self.cleanup_local(project_name) # 既存があれば消す

        self.docker_client.containers.run(tag, name=container_name, ports={'8080/tcp': 8080}, detach=True)
        return "http://localhost:8080"

    def cleanup_local(self, project_name: str) -> str:
        container_name = f"{project_name}-dev"
        try:
            container = self.docker_client.containers.get(container_name)
            print(f"🧹 Stopping & Removing local container: {container_name}")
            container.stop()
            container.remove()
            return "✅ Local container destroyed."
        except docker.errors.NotFound:
            return "⚠️ Container not found (already deleted)."

    # --- Lambda Mode ---
    def build_and_push_lambda(self, build_dir: str, project_name: str) -> str:
        repo_uri = self._ensure_ecr_repo(project_name)
        tag = f"{repo_uri}:latest"
        
        print(f"🐳 Building for Lambda: {tag}")
        self.docker_client.images.build(path=str(build_dir), tag=tag)
        
        # ECR Login
        auth = self.ecr.get_authorization_token()['authorizationData'][0]
        token = base64.b64decode(auth['authorizationToken']).decode('utf-8').split(':')
        self.docker_client.login(token[0], token[1], registry=repo_uri.split('/')[0])
        
        print(f"🚀 Pushing to ECR...")
        self.docker_client.images.push(tag)
        return repo_uri

    def deploy_to_lambda(self, project_name: str, image_uri: str) -> str:
        func_name = f"{project_name}-func"
        role_arn = self._ensure_role("SmartDeployLambdaRole")
        
        print(f"⚡ Deploying Function: {func_name}")
        try:
            self.lambda_client.update_function_code(FunctionName=func_name, ImageUri=image_uri, Publish=True)
            time.sleep(5)
        except self.lambda_client.exceptions.ResourceNotFoundException:
            self.lambda_client.create_function(
                FunctionName=func_name, PackageType='Image', Code={'ImageUri': image_uri},
                Role=role_arn, Timeout=30, MemorySize=512, Architectures=['x86_64']
            )
            time.sleep(10)

        # URL公開設定
        try:
            self.lambda_client.create_function_url_config(FunctionName=func_name, AuthType='NONE')
            self.lambda_client.add_permission(FunctionName=func_name, StatementId='PublicAccess', Action='lambda:InvokeFunctionUrl', Principal='*', FunctionUrlAuthType='NONE')
        except self.lambda_client.exceptions.ResourceConflictException: 
            pass
        
        return self.lambda_client.get_function_url_config(FunctionName=func_name)['FunctionUrl']

    def cleanup_lambda(self, project_name: str) -> str:
        """Lambda関数を削除 (ECRイメージはキャッシュのため残す)"""
        func_name = f"{project_name}-func"
        try:
            print(f"🔥 Deleting Lambda function: {func_name}")
            self.lambda_client.delete_function(FunctionName=func_name)
            return f"✅ Lambda function '{func_name}' destroyed."
        except self.lambda_client.exceptions.ResourceNotFoundException:
            return "⚠️ Function not found (already deleted)."

    def _ensure_ecr_repo(self, name):
        try: 
            return self.ecr.describe_repositories(repositoryNames=[name])['repositories'][0]['repositoryUri']
        except self.ecr.exceptions.RepositoryNotFoundException:  
            return self.ecr.create_repository(repositoryName=name)['repository']['repositoryUri']

    def _ensure_role(self, name):
        try: 
            return self.iam.get_role(RoleName=name)['Role']['Arn']
        except self.iam.exceptions.NoSuchEntityException:
            policy = json.dumps({"Version": "2012-10-17","Statement": [{"Effect": "Allow","Principal": {"Service": "lambda.amazonaws.com"},"Action": "sts:AssumeRole"}]})
            res = self.iam.create_role(RoleName=name, AssumeRolePolicyDocument=policy)
            self.iam.attach_role_policy(RoleName=name, PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")
            time.sleep(10)
            return res['Role']['Arn']