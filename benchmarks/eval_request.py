import argparse
import requests
import json
import re
import sys
import paddle

try:
    import fastdeploy
except ImportError:
    fastdeploy = None


def get_commits_from_fastdeploy():
    """
    解析 fastdeploy.utils.version() 输出中的 commit ID
    """
    if not fastdeploy:
        return None, None

    try:
        version_text = fastdeploy.utils.version()
        fd_commit_match = re.search(r"fastdeploy GIT COMMIT ID:\s*([0-9a-f]{7,40})", version_text)
        fd_commit = fd_commit_match.group(1) if fd_commit_match else None
        paddle_commit = getattr(paddle, "__git_commit__", None)
        return fd_commit, paddle_commit
    except Exception as e:
        print("无法获取 fastdeploy 版本信息:", e)
        return None, None


def main():
    parser = argparse.ArgumentParser(description="Send JSON POST request to /aibench/create")

    parser.add_argument("--url", required=True, help="目标URL")
    parser.add_argument("--name", required=True, help="任务名称")
    parser.add_argument("--model_id", default="eb5_ce", help="模型ID")
    parser.add_argument("--paddle_commit", default="paddle_commit", help="Paddle commit ID")
    parser.add_argument("--fd_commit", default="fd_commit", help="FD commit ID")
    parser.add_argument("--mode", default="test", help="运行模式，默认：test")

    args = parser.parse_args()

    # 读取 fastdeploy/paddle commit
    auto_fd_commit, auto_paddle_commit = get_commits_from_fastdeploy()

    fd_commit = auto_fd_commit or args.fd_commit or "unknown_fd"
    paddle_commit = auto_paddle_commit or args.paddle_commit or "unknown_paddle"

    headers = {"Content-Type": "application/json"}
    data = {
        "name": args.name,
        "model_id": args.model_id,
        "paddle_commit": paddle_commit,
        "fd_commit": fd_commit,
        "mode": args.mode,
    }

    print(f"url: {args.url}")
    print(f"请求数据: {json.dumps(data, ensure_ascii=False, indent=2)}")

    try:
        response = requests.post(args.url, headers=headers, json=data, timeout=10)
        print("状态码:", response.status_code)
        try:
            print("响应内容:", json.dumps(response.json(), ensure_ascii=False, indent=2))
        except Exception:
            print("响应内容(非JSON):", response.text)
    except requests.exceptions.RequestException as e:
        print("请求失败:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
