import boto3
import docker
import base64
from config import settings

class ExecutionEngine:
    def __init__(self):
        self.ecr = boto3.client('ecr', region_name=settings.AWS_REGION)
        self.apprunner = boto3.client('apprunner', region_name=settings.AWS_REGION)
        self.ec2 = boto3.client('ec2', region_name=settings.AWS_REGION)
        self.docker_client = docker.from_env()

    def ensure_ecr_repo(self, repo_name: str) -> str:
        """既存リポジトリを確認・作成 (Live Context)"""
        try:
            res = self.ecr.describe_repositories(repositoryNames=[repo_name])
            print(f"♻️ Existing ECR repo found: {repo_name}")
            return res['repositories'][0]['repositoryUri']
        except self.ecr.exceptions.RepositoryNotFoundException:
            print(f"🆕 Creating new ECR repo: {repo_name}")
            res = self.ecr.create_repository(repositoryName=repo_name)
            return res['repository']['repositoryUri']

    def _login_to_ecr(self, target_registry: str):
        """
        Docker SDKでECRにログインする。
        target_registry: プッシュ先のレジストリURI (例: 123456789012.dkr.ecr.us-east-1.amazonaws.com)
        """
        try:
            # 1. 認証トークン取得
            response = self.ecr.get_authorization_token()
            token_data = response['authorizationData'][0]
            
            # 2. 認証されたエンドポイントを取得
            authenticated_endpoint = token_data['proxyEndpoint'] 
            
            # target_registry (httpsなし) が authenticated_endpoint (httpsあり) に含まれているか確認
            if target_registry not in authenticated_endpoint:
                print(f"⚠️ Warning: Target registry ({target_registry}) does not match authenticated endpoint ({authenticated_endpoint}).")
                # ここでエラーにするか、警告で進むかはポリシー次第ですが、今回は警告のみとします
            
            # 3. ログイン実行
            auth_token = base64.b64decode(token_data['authorizationToken']).decode('utf-8')
            username, password = auth_token.split(':')
            
            print(f"🔑 Logging in to ECR: {authenticated_endpoint} ...")
            self.docker_client.login(
                username=username,
                password=password,
                registry=authenticated_endpoint
            )
            print("✅ ECR Login Succeeded.")
            
        except Exception as e:
            print(f"❌ ECR Login Failed: {e}")
            raise e

    def build_and_push(self, build_dir: str, repo_uri: str):
        """Dockerビルド & Push (認証付き)"""
        tag = f"{repo_uri}:latest"
        
        # 1. ビルド
        print(f"🐳 Building Docker image: {tag} ...")
        # docker build -t tag path
        image, logs = self.docker_client.images.build(path=str(build_dir), tag=tag)
        for chunk in logs:
            if 'stream' in chunk:
                print(chunk['stream'].strip())

        # 2. ログイン
        # repo_uri (123456.dkr.ecr...) からレジストリURLを抽出してログイン
        registry = repo_uri.split('/')[0]
        self._login_to_ecr(registry)

        # 3. プッシュ
        print(f"🚀 Pushing to ECR: {tag} ...")
        # pushのログはジェネレータで返るため、ループで回して表示
        for line in self.docker_client.images.push(tag, stream=True, decode=True):
            if 'status' in line:
                print(f"{line.get('status')} {line.get('progress', '')}")
        
        print("✅ Push Completed!")

    def hunt_zombies(self) -> list[str]:
        """未使用EBSの検出"""
        zombies = []
        try:
            volumes = self.ec2.describe_volumes(Filters=[{'Name': 'status', 'Values': ['available']}])
            for v in volumes['Volumes']:
                zombies.append(f"🧟 Unused EBS: {v['VolumeId']} ({v['Size']}GB)")
        except Exception:
            pass
        return zombies