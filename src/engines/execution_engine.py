import subprocess
import boto3
import docker
import sys
from config import settings

class ExecutionEngine:
    def __init__(self):
        # ローカル実行用のためのDockerクライアント初期化
        self.docker_client = docker.from_env()
        
        # デプロイ後のURL取得をCloudFormation経由で行うためBoto3クライアント初期化
        if settings.HAS_AWS_CREDS:
            self.cf_client = boto3.client('cloudformation', region_name=settings.AWS_REGION)

    # --- Local Mode ---
    def deploy_to_local(self, build_dir: str, project_name: str) -> str:
        """
        ローカルPC上でDockerコンテナをビルド・起動する
        """

        tag = f"{project_name}:local"
        container_name = f"{project_name}-dev"
        print(f"🏠 Local Build & Run: {tag}", file=sys.stderr)
        self.docker_client.images.build(path=str(build_dir), tag=tag)
        self.cleanup_local(project_name) 
        self.docker_client.containers.run(tag, name=container_name, ports={'8080/tcp': 8080}, detach=True)
        return "http://localhost:8080"

    def cleanup_local(self, project_name: str) -> str:
        """
        ローカルDockerコンテナの停止・削除
        """
        container_name = f"{project_name}-dev"
        try:
            container = self.docker_client.containers.get(container_name)
            container.stop()
            container.remove()
            return "✅ Local container destroyed."
        except docker.errors.NotFound:
            return "⚠️ Container not found."

    # --- Lambda Mode (SAMへ移行) ---
    def build_and_push_lambda(self, build_dir: str, project_name: str) -> str:
        """
        AWS SAMを使用しイメージのビルドとECRへのプッシュを行う。
        """

        print(f"🔨 Building with AWS SAM...", file=sys.stderr)
        
        # 'sam build' コマンドを実行
        # template.yaml は build_dir に生成されている前提
        try:
            subprocess.run(
                ["sam", "build"], 
                cwd=str(build_dir), 
                check=True,
                capture_output=False  # ログを標準出力に出す
            )
        except subprocess.CalledProcessError as e:
             raise Exception(f"❌ SAM Build Failed: {e}")

        return "Build Complete (Image will be pushed during deploy)"

    def deploy_to_lambda(self, project_name: str, image_uri: str = None) -> str:
        """
        AWS SAMを使用しLambdaへデプロイを実施

        """
        print(f"🚀 Deploying to AWS Lambda with SAM...", file=sys.stderr)
        work_dir = settings.WORK_DIR

        # SAM Deploy コマンド
        cmd = [
            "sam", "deploy",
            "--stack-name", project_name,
            "--resolve-s3",
            "--resolve-image-repos",
            "--capabilities", "CAPABILITY_IAM",
            "--no-confirm-changeset",
            "--no-fail-on-empty-changeset"
        ]

        try:
            subprocess.run(cmd, cwd=str(work_dir), check=True)
            
            # デプロイ完了後、CloudFormationのOutputsからURLを取得
            return self._fetch_stack_output(project_name, "FunctionUrl")
            
        except subprocess.CalledProcessError as e:
            raise Exception(f"❌ SAM Deploy Failed: {e}")

    def cleanup_lambda(self, project_name: str) -> str:
        """
        AWS SAMを使用し、デプロイしたスタックを全て削除
        """

        print(f"🔥 Destroying Stack: {project_name}", file=sys.stderr)
        cmd = [
            "sam", "delete",
            "--stack-name", project_name,
            "--no-prompts"
        ]
        try:
            subprocess.run(cmd, cwd=str(settings.WORK_DIR), check=True)
            return f"✅ Stack '{project_name}' destroyed."
        except subprocess.CalledProcessError:
            return "⚠️ Delete failed or stack not found."

    def _fetch_stack_output(self, stack_name: str, output_key: str) -> str:
        """CloudFormationスタックのOutputsから特定の値を取得"""
        try:
            response = self.cf_client.describe_stacks(StackName=stack_name)
            outputs = response['Stacks'][0].get('Outputs', [])
            for o in outputs:
                if o['OutputKey'] == output_key:
                    return o['OutputValue']
        except Exception as e:
            print(f"⚠️ Failed to fetch output: {e}", file=sys.stderr)
        return "URL not found"