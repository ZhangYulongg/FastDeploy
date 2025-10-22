import argparse
import requests
import time
import json
import re
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


def create_eval_task(base_url: str, name: str, model_id: str, paddle_commit: str, fd_commit: str, mode: str = "test", timeout: int = 10):
    """
    创建评测任务（POST /aibench/create）
    """
    url = f"{base_url.rstrip('/')}/aibench/create"
    headers = {"Content-Type": "application/json"}
    data = {
        "name": name,
        "model_id": model_id,
        "paddle_commit": paddle_commit,
        "fd_commit": fd_commit,
        "mode": mode,
    }

    print(f"📤 发送 POST 请求到: {url}")
    print("请求数据:", json.dumps(data, ensure_ascii=False, indent=2))

    try:
        response = requests.post(url, headers=headers, json=data, timeout=timeout)
        print("状态码:", response.status_code)

        try:
            result = response.json()
            print("响应内容:", json.dumps(result, ensure_ascii=False, indent=2))
            return result
        except Exception:
            print("响应内容(非JSON):", response.text)
            return None

    except requests.exceptions.RequestException as e:
        print("❌ 请求失败:", e)
        return None


def query_task_detail(base_url: str, eval_id: int, timeout: int = 10):
    """
    查询评测任务详情（QueryTaskDetail）
    """
    url = f"{base_url.rstrip('/')}/aibench/details"
    headers = {"Content-Type": "application/json"}
    data = {"eval_id": eval_id}

    try:
        response = requests.get(url, headers=headers, params=data, timeout=timeout)
        print("状态码:", response.status_code)
        try:
            result = response.json()
            print("响应内容:", json.dumps(result, ensure_ascii=False, indent=2))
            return result
        except Exception:
            print("响应内容(非JSON):", response.text)
            return None
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return None


def wait_for_task_completion(base_url: str, eval_id: int, check_interval: int = 300, max_wait: int = 25200):
    """
    每隔一段时间轮询查询任务详情，
    若所有子任务的 original_status_message 包含 “成功” / “失败” / “终止”，则结束阻塞。
    超时后自动退出。

    参数:
        base_url (str): 接口基础地址
        eval_id (int): 任务ID
        check_interval (int): 轮询间隔秒数（默认5分钟=300秒）
        max_wait (int): 最大等待时间（秒，默认7小时=25200秒）
    """
    keywords = ["成功", "失败", "终止"]
    start_time = time.time()

    while True:
        result = query_task_detail(base_url, eval_id)

        if not result or "data" not in result:
            print("⚠️ 获取任务信息失败，5分钟后重试...")
            time.sleep(check_interval)
            continue

        tasks = result["data"].get("tasks", [])
        if not tasks:
            print("⚠️ 无任务详情，等待中...")
            time.sleep(check_interval)
            continue

        # 检查每个任务是否都含有目标关键词，并统计完成数量
        completed_count = 0
        for t in tasks:
            msg = t.get("original_status_message", "")
            if any(k in msg for k in keywords):
                completed_count += 1

        total_tasks = len(tasks)
        print(f"⌛ 当前进度: {completed_count}/{total_tasks} 个任务已完成（含成功/失败/终止）")

        if completed_count == total_tasks:
            print("✅ 所有任务已完成，结束等待。")
            break
        else:
            print(f"⏳ 仍有任务未完成，{check_interval//60}分钟后重试...")
            time.sleep(check_interval)

        elapsed = time.time() - start_time
        if elapsed > max_wait:
            print(f"⏰ 等待超时（{max_wait}秒），退出轮询。")
            break

    return result


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

    # 调用封装的函数创建任务
    result = create_eval_task(
        base_url=args.url,
        name=args.name,
        model_id=args.model_id,
        paddle_commit=paddle_commit,
        fd_commit=fd_commit,
        mode=args.mode,
    )

    if result and "data" in result and "eval_id" in result["data"]:
        eval_id = result["data"]["eval_id"]
        print(f"🎯 创建成功，任务ID: {eval_id}")
        wait_for_task_completion(args.url, eval_id)
    else:
        print("⚠️ 未获取到 eval_id，无法进入轮询。")


if __name__ == "__main__":
    main()
