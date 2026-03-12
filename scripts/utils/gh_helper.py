import subprocess
import json
import os

class GitHubHelper:
    """
    GitHub CLI(gh)를 직접 호출하여 토큰을 아끼는 AI 전용 도우미 클래스입니다.
    """
    
    @staticmethod
    def run_gh(args):
        """gh 명령어를 실행하고 결과를 반환합니다."""
        try:
            cmd = ["gh"] + args
            # 윈도우 환경에서 쉘 실행 지원
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                encoding='utf-8', 
                shell=True
            )
            
            if result.returncode != 0:
                return {"error": result.stderr.strip()}
            
            # JSON 결과인 경우 파싱하여 반환
            if "--json" in args:
                try:
                    data = json.loads(result.stdout)
                    return GitHubHelper._trim_data(data)
                except json.JSONDecodeError:
                    pass
                    
            return result.stdout.strip()
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _trim_data(data):
        """
        AI가 읽을 때 토큰을 낭비하는 불필요한 메타데이터(URL, 이메일, 타임스탬프 등)를 삭제합니다.
        """
        if isinstance(data, list):
            return [GitHubHelper._trim_data(item) for item in data]
        if isinstance(data, dict):
            # 토큰을 많이 먹는 필드 목록 (제외 대상)
            exclude_keys = ["url", "html_url", "node_id", "gravatar_id", "events_url", "received_events_url", "organizations_url", "repos_url", "followers_url", "following_url", "gists_url", "starred_url", "subscriptions_url"]
            return {k: GitHubHelper._trim_data(v) for k, v in data.items() if k not in exclude_keys}
        return data

# 예제 사용법:
# gh = GitHubHelper()
# prs = gh.run_gh(["pr", "list", "--limit", "3", "--json", "number,title,state"])
# print(json.dumps(prs, indent=2))
