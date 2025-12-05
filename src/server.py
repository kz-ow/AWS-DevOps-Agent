import textwrap
from fastmcp import FastMCP
from config import settings
from engines.analysis_engine import AnalysisEngine
from engines.decision_engine import DecisionEngine
from engines.execution_engine import ExecutionEngine
from llama_index.core import Settings as LlamaSettings

# エンジン初期化
analyzer = AnalysisEngine()
decider = DecisionEngine()
executor = ExecutionEngine()

mcp = FastMCP("PersonalDevOpsPartner")

# --- 1. 計画フェーズ (Plan) ---
@mcp.tool()
def plan_deployment(repo_url: str, target: str = "local") -> str:
    """
    【Step 1】デプロイ計画を作成します。
    リポジトリを解析し、アーキテクチャ図(Mermaid)を表示します。
    まだデプロイは実行されません。ユーザーの承認を求めてください。
    
    Args:
        repo_url: GitHubリポジトリURL
        target: 'local' (PCで起動) or 'lambda' (AWSサーバーレス)
    """
    print(f"🔍 Planning deployment: {repo_url} [{target}]")
    
    # 解析 & 生成 (まだデプロイしない)
    work_dir = analyzer.clone_repository(repo_url)
    context = analyzer.analyze_context(work_dir)
    dockerfile = decider.generate_dockerfile(context, 0, "", target)
    (work_dir / "Dockerfile").write_text(dockerfile)
    
    # 図解 (Mermaid)
    print("🎨 Drawing Architecture Plan...")
    diagram = LlamaSettings.llm.complete(
        f"Create a mermaid graph TD for a proposed {target} deployment of {context['stack_summary']}. Return ONLY mermaid code."
    ).text.replace("```mermaid", "").replace("```", "").strip()

    return textwrap.dedent(
    f"""
    # 📋 Deployment Plan

    コードを分析し，デプロイ環境のアーキテクチャ図を作成しました。
    **まだデプロイは実行していません**

    ## 🏗 作成したデプロイ環境
    ```mermaid
    {diagram}
    ```
    🛠 Configuration
    Target: {target.upper()}

    Stack: {context['stack_summary']}

    Dockerfile: Generated in {work_dir}

    ❓ 次のステップ: ユーザーに「デプロイを実行してもよろしいですか？」と尋ねてください。承認された場合は apply_deployment を呼び出してください。
    """
    )

# --- 2. 実行フェーズ (Apply) ---
@mcp.tool()
def apply_deployment(project_name: str, target: str = "local") -> str:
    """ 
   【Step 2】承認された計画を実行(デプロイ)します。 必ず plan_deployment の後に実行してください。
    
    Args:
        project_name: プロジェクト名 (英数字推奨)
        target: 'local' or 'lambda'
    """

    print(f"🚀 Applying deployment: {project_name} [{target}]")
    work_dir = settings.WORK_DIR

    # 計画ファイル（Dockerfile）の存在確認
    if not (work_dir / "Dockerfile").exists():
        return "❌ Error: No deployment plan found. Please run `plan_deployment` first."

    status_msg = ""
    deploy_url = ""

    if target == "local":
        deploy_url = executor.deploy_to_local(work_dir, project_name)
        status_msg = "✅ Local Container Running"
    elif target == "lambda":
        if not settings.HAS_AWS_CREDS:
            return "❌ Error: AWS Credentials missing. Please set up ~/.aws or use target='local'."
        
        # AWS Lambdaデプロイ (ビルド -> Push -> 関数更新)
        image_uri = executor.build_and_push_lambda(work_dir, project_name)
        deploy_url = executor.deploy_to_lambda(project_name, image_uri)
        status_msg = "🎉 Deployed to AWS Lambda"

    return f"""
    🚀 Deployment Successful!
    ・Status: {status_msg}
    ・URL: {deploy_url}

    You can verify the application now. To clean up resources, run destroy_resources. 
    """

# --- 3. 破棄フェーズ (Destroy) ---
@mcp.tool()
def destroy_resources(project_name: str, target: str = "local") -> str:
    """
    【Step 3】デプロイしたリソースを破棄します。
    
    Args:
        project_name: プロジェクト名
        target: 'local' or 'lambda'
    """
    print(f"🧹 Destroying resources for: {project_name} [{target}]")
    status_msg = ""

    if target == "local":
        status_msg = executor.cleanup_local(project_name)
    elif target == "lambda":
        if not settings.HAS_AWS_CREDS:
            return "❌ Error: AWS Credentials missing. Cannot destroy Lambda resources."
        
        status_msg = executor.cleanup_lambda(project_name)
    return f"""
    🧹 Resource Cleanup Complete!
    ・Status: {status_msg}
    """

if __name__ == "__main__":
    mcp.run()