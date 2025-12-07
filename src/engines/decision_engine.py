import subprocess
import tempfile
import os
import json
import sys
from llama_index.core import Settings as LlamaSettings

class DecisionEngine:
    def generate_dockerfile(self, context: dict, attempt: int, error_msg: str, target_service: str) -> str:
        """
        コンテキストとターゲット環境に基づいてLLMでDockerfileを生成
        ターゲットがAWS Lambdaの場合，AWS Lambda Web Adapterの追加を指示
        """
        stack = context.get('stack_summary', 'Unknown Stack')
        rules = context.get('security_context', 'Standard best practices')
        
        prompt = f"""
        You are a DevOps Expert. Generate a production-ready 'Dockerfile' for the following application.
        
        [Tech Stack]
        {stack}
        
        [Security Rules]
        {rules}
        
        [Feedback from previous attempt]
        {error_msg if error_msg else "None (First attempt)"}
        """

        # Lambda対応: AWS Lambda Web Adapter の自動注入
        if target_service == "lambda":
            prompt += """
            \n[IMPORTANT: AWS Lambda Deployment]
            This container will run on AWS Lambda.
            You MUST add the following line to the Dockerfile to handle HTTP requests:
            COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.8.4 /lambda-adapter /opt/extensions/lambda-adapter
            
            Ensure the ENTRYPOINT or CMD starts the web server on port 8080 (default).
            """
        
        prompt += "\nOutput ONLY the Dockerfile content. No markdown code blocks, no explanations."
        
        # LLMに生成させる
        response = LlamaSettings.llm.complete(prompt)
        return response.text.replace("```dockerfile", "").replace("```", "").strip()
    
    def generate_sam_template(self, project_name: str, error_msg: str = "") -> str:
        """
        LLMでAWS SAMテンプレートを生成
        SAMによる自動ビルドを利用するため、ImageUriは指定せずMetadataを付与するよう指示
        """
        
        prompt = f"""
        You are an AWS DevOps Expert. Generate an AWS SAM template (template.yaml) for a serverless application.
        
        [Project Name]
        {project_name}
        
        [Requirements]
        1. Create a Lambda function resource ('AWS::Serverless::Function').
        2. Use 'PackageType: Image'.
        3. DO NOT specify 'ImageUri'. Instead, use the 'Metadata' section to configure the build:
           - Dockerfile: Dockerfile
           - DockerContext: .
           - DockerTag: latest
        4. Enable a public Function URL (AuthType: NONE).
        5. Add 'AWSLambdaBasicExecutionRole' to Policies.
        6. Output the Function URL in the 'Outputs' section.
        7. Set MemorySize to 512 and Timeout to 30.
        8. Architecture should be x86_64.

        Output ONLY the SAM template content in YAML format. No markdown code blocks, no explanations.
        """
        
        response = LlamaSettings.llm.complete(prompt)
        return response.text.replace("```yaml", "").replace("```", "").strip()

    def audit_dockerfile(self, content: str, service: str) -> list[str]:
        """
        生成されたDockerfileを一時ファイルに保存
        Hadolint (Lint) と Trivy (脆弱性スキャン) を実行して監査
        ツールで検知できない論理エラーはAIが最終確認
        """
        violations = []

        # 解析のために一時ファイルとして保存
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            # --- 1. Hadolint (Dockerfile Lint) ---
            # 構文エラーやベストプラクティス違反をチェック
            try:
                result = subprocess.run(
                    ['hadolint', '--no-fail', '--format', 'json', tmp_path],
                    capture_output=True, text=True
                )
                if result.stdout:
                    errors = json.loads(result.stdout)
                    for err in errors:
                        # infoレベルは無視し、warning以上を指摘
                        if err['level'] in ['error', 'warning']:
                            violations.append(f"[Hadolint] {err['code']}: {err['message']} (Line {err['line']})")
            except FileNotFoundError:
                print("⚠️ Hadolint not installed. Skipping lint check.", file=sys.stderr)
            except json.JSONDecodeError:
                pass

            # --- 2. Trivy (Config Audit) ---
            # 既知の脆弱性や設定ミス（秘密情報の混入など）をスキャン（静的解析）
            try:
                trivy_cmd = [
                    'trivy', 'config',
                    '--format', 'json',
                    '--severity', 'HIGH,CRITICAL',
                    tmp_path
                ]
                result = subprocess.run(trivy_cmd, capture_output=True, text=True)
                
                if result.returncode == 0 and result.stdout:
                    scan_result = json.loads(result.stdout)
                    if 'Results' in scan_result:
                        for res in scan_result['Results']:
                            if 'Misconfigurations' in res:
                                for misconf in res['Misconfigurations']:
                                    violations.append(f"[Trivy] {misconf['ID']}: {misconf['Description']}")
            except FileNotFoundError:
                print("⚠️ Trivy not installed. Skipping security scan.", file=sys.stderr)
            except json.JSONDecodeError:
                pass

        finally:
            # 一時ファイルのお掃除
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        # --- 3. AIによる論理チェック (Fallback) ---
        # ツールで問題がない場合：Lambda Adapterが入っているか確認
        if not violations:
            audit_prompt = f"""
            Audit this Dockerfile logic for {service}. 
            If target is 'lambda', check if 'aws-lambda-adapter' is COPY-ed.
            Return 'PASS' if safe and requirements met, else briefly explain the missing part.
            
            {content}
            """
            res = LlamaSettings.llm.complete(audit_prompt).text.strip()
            
            if "PASS" not in res:
                violations.append(f"[AI Logic Check] {res}")

        return violations
    

    def audit_sam_template(self, template_content: str) -> list[str]:
        """
        SAMテンプレートの静的解析 (cfn-lint & Checkov/Trivy)
        """
        violations = []
        
        # 一時ファイル作成
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
            tmp.write(template_content)
            tmp_path = tmp.name

        try:
            # --- 1. cfn-lint (構文チェック) ---
            # AWS公式のバリデータ。必須パラメータ不足などを検知
            res = subprocess.run(
                ['cfn-lint', '--format', 'json', tmp_path],
                capture_output=True, text=True
            )
            
            # cfn-lintはエラーがあるとき非0を返す
            if res.stdout:
                try:
                    errors = json.loads(res.stdout)
                    for err in errors:
                        violations.append(f"[cfn-lint] {err['Level']}: {err['Message']} (Line {err['Location']['Start']['LineNumber']})")
                except json.JSONDecodeError:
                    pass

            # --- 2. Trivy (セキュリティスキャン) ---
            # TrivyはIaCスキャン機能を持っています
            trivy_cmd = [
                'trivy', 'config',
                '--format', 'json',
                '--severity', 'HIGH,CRITICAL',
                tmp_path
            ]
            res = subprocess.run(trivy_cmd, capture_output=True, text=True)
            if res.stdout:
                try:
                    scan_result = json.loads(res.stdout)
                    if 'Results' in scan_result:
                        for r in scan_result['Results']:
                            if 'Misconfigurations' in r:
                                for m in r['Misconfigurations']:
                                    violations.append(f"[Trivy IaC] {m['ID']}: {m['Description']}")
                except json.JSONDecodeError:
                    pass

        finally:
            os.remove(tmp_path)
            
        return violations