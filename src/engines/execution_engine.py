import boto3
import docker
import base64
import json
import time
import sys # 追加: ログ出力用
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
        # LocalでもAMD64にしておくと互換性が高いが、ローカル実行速度優先ならplatform指定なしでもOK
        self.docker_client.images.build(path=str(build_dir), tag=tag)
        self.cleanup_local(project_name) 

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
        # ECRプッシュ用のタグ
        tag = f"{repo_uri}:latest"
        
        print(f"🐳 Building for Lambda (linux/amd64): {tag}")
        
        # 【重要修正1】Lambda用にプラットフォームを linux/amd64 に固定
        # これをしないと、M1 Mac等で作ったイメージがLambdaで動きません
        self.docker_client.images.build(
            path=str(build_dir), 
            tag=tag,
            platform="linux/amd64" 
        )
        
        # ECR Login
        auth = self.ecr.get_authorization_token()['authorizationData'][0]
        token = base64.b64decode(auth['authorizationToken']).decode('utf-8').split(':')
        self.docker_client.login(token[0], token[1], registry=repo_uri.split('/')[0])
        
        print(f"🚀 Pushing to ECR: {tag}")
        
        # 【重要修正2】プッシュの完了を待ち、エラーをチェックする
        # stream=True, decode=True でログを一行ずつ読み取る
        push_logs = self.docker_client.images.push(tag, stream=True, decode=True)
        
        for line in push_logs:
            # エラーがある場合は例外を投げる
            if 'error' in line:
                error_msg = line['errorDetail']['message']
                raise Exception(f"❌ Docker Push Failed: {error_msg}")
            
            # 進捗を表示 (任意: ログが長くなりすぎるならコメントアウト)
            if 'status' in line:
                print(f"  > {line['status']}", end='\r')
        
        print(f"\n✅ Push complete: {tag}")
        return repo_uri

    def deploy_to_lambda(self, project_name: str, image_uri: str) -> str:
        # pushした画像URIにタグをつける
        image_uri_with_tag = f"{image_uri}:latest"
        
        func_name = f"{project_name}-func"
        role_arn = self._ensure_role("SmartDeployLambdaRole")
        
        print(f"⚡ Deploying Function: {func_name}")
        try:
            # 更新処理
            self.lambda_client.update_function_code(
                FunctionName=func_name, 
                ImageUri=image_uri_with_tag, # タグ付きを指定
                Publish=True
            )
            
            # 更新完了を少し待つ (本来はwaiterを使うのがベスト)
            print("⏳ Waiting for function update...")
            time.sleep(10)
            
        except self.lambda_client.exceptions.ResourceNotFoundException:
            # 新規作成
            print("🆕 Creating new function...")
            # 作成直後はRoleの反映待ちが必要な場合があるためリトライループ推奨だが、簡易的にsleep
            time.sleep(5) 
            
            self.lambda_client.create_function(
                FunctionName=func_name,
                PackageType='Image',
                Code={'ImageUri': image_uri_with_tag}, # タグ付きを指定
                Role=role_arn,
                Timeout=30,
                MemorySize=512,
                Architectures=['x86_64']
            )
            print("⏳ Waiting for function creation...")
            time.sleep(10)

        # URL公開設定
        try:
            self.lambda_client.create_function_url_config(
                FunctionName=func_name, 
                AuthType='NONE'
            )
            self.lambda_client.add_permission(
                FunctionName=func_name, 
                StatementId='PublicAccess', 
                Action='lambda:InvokeFunctionUrl', 
                Principal='*', 
                FunctionUrlAuthType='NONE'
            )
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
            policy = json.dumps({
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {"Service": "lambda.amazonaws.com"},
                    "Action": "sts:AssumeRole"
                }]
            })
            res = self.iam.create_role(RoleName=name, AssumeRolePolicyDocument=policy)
            self.iam.attach_role_policy(RoleName=name, PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")
            # Role作成直後はLambdaが認識できないことがあるので長めに待つ
            print("⏳ Waiting for IAM Role propagation...")
            time.sleep(15) 
            return res['Role']['Arn']