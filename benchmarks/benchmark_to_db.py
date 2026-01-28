#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
upload_benchmark_result.py
解析 benchmark_report.txt 并上传至 FastDeploy CE 接口
"""

import re
import json
import argparse
import os
import requests
from datetime import datetime


def get_commits_from_files(fd_path="fd_commit.txt", paddle_commit_file="paddle_commit.txt"):
    """分别从 fd_commit.txt 和 paddle_commit_file 中读取 commit id"""
    fd_commit = "unknown"
    pd_commit = "unknown"

    # 读取 fastdeploy version 文件
    if os.path.exists(fd_path):
        try:
            with open(fd_path, "r", encoding="utf-8") as f:
                content = f.read()
                fd_match = re.search(r"fastdeploy GIT COMMIT ID:\s*([0-9a-f]{7,40})", content)
                if fd_match:
                    fd_commit = fd_match.group(1)
        except Exception as e:
            print(f"[warn] 读取 {fd_path} 失败: {e}")

    # 读取 paddle commit 文件
    if os.path.exists(paddle_commit_file):
        try:
            with open(paddle_commit_file, "r", encoding="utf-8") as f:
                text = f.read().strip()
                m = re.search(r"([0-9a-f]{7,40})", text)
                if m:
                    pd_commit = m.group(1)
        except Exception as e:
            print(f"[warn] 读取 {paddle_commit_file} 失败: {e}")

    return fd_commit, pd_commit


def parse_benchmark_report(args):
    with open(args.benchmark_file, "r", encoding="utf-8") as f:
        content = f.read()

    def extract(pattern, to_float=True):
        m = re.search(pattern, content)
        if not m:
            return None
        val = m.group(1).replace(",", "")
        return float(val) if to_float else val

    max_gpu = 0
    max_bs = 0
    max_block = 0
    with open(f"{args.log_dir}/default.gpu.log", "r") as f1:
        for line1 in f1:
            if ",202" in line1:
                line_tmp = line1.strip().split(",")[3]
                gpu = line_tmp.strip()
                max_gpu = max(int(gpu), max_gpu)
    print("gpu_memory:{}".format(max_gpu))
    with open(f"{args.log_dir}/workerlog.0", "r") as f_worker:
        for line in f_worker:
            if "Model loading took" in line:
                match = re.search(r'took\s+(\d+\.\d+)\s+seconds', line)
                if match:
                    time_value = match.group(1)
                    print("loading_time:{}".format(round(float(time_value), 2)))
    with open(f"{args.log_dir}/worker_process.log", "r") as f_process:
        for line in f_process:
            match = re.search(r'num_blocks_global:\s*(\d+)', line)
            if match:
                number = match.group(1)
                max_block = max(int(number), max_block)
    with open(f"{args.log_dir}/log_0/fastdeploy_dprank0.log", "r") as f_process:
        for line in f_process:
            match = re.search(r'total_batch_number:\s*(\d+)', line)
            match_bs = re.search(r'available_batch:\s*(\d+)', line)
            if match_bs:
                total_batch_number = match.group(1)
                available_batch = match_bs.group(1)
                max_bs = max(int(total_batch_number) - int(available_batch), max_bs)

    data = {
        "receive_num": extract(r"Successful requests:\s+(\d+)", False),
        "qps": extract(r"Request throughput \(req/s\):\s+([\d.]+)"),
        "tps": extract(r"Total Token throughput \(tok/s\):\s+([\d.]+)"),
        "decode": extract(r"Mean Decode:\s+([\d.]+)"),
        "first_token_time": extract(r"Mean TTFT \(ms\):\s+([\d.]+)"),
        "infer_first_token_time": extract(r"Mean S_TTFT \(ms\):\s+([\d.]+)"),
        "end_to_end_latency": extract(r"Mean E2EL \(ms\):\s+([\d.]+)"),
        "infer_end_to_end_latency": extract(r"Mean S_E2EL \(ms\):\s+([\d.]+)"),
        "inter_token_latency": extract(r"Mean S_ITL \(ms\):\s+([\d.]+)"),
        "input_length": extract(r"Mean Input Length:\s+([\d.]+)"),
        "output_length": extract(r"Mean Output Length:\s+([\d.]+)"),
        # "reasoning_length": extract(r"Mean Reasoning Lenth:\s+([\d.]+)"),
        "gpu": max_gpu,
        "loading_time": time_value,
        "block_num": max_block,
        "real_bs": max_bs,
    }

    return data


def post_to_fastdeploy_ce(url, parsed_data, meta_info=None):
    fd_commit, pd_commit = get_commits_from_files()

    meta_defaults = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "model": "None",
        "infer_type": "None",
        "deploy_type": "集中式部署",
        "infer_length": "None",
        "paddle_commit": pd_commit,
        "fastdeploy_commit": fd_commit,
        "machine": "None",
        "tp_num": "None",
        "ipipe": "None",
        "branch": "None",
        "chunked_prefilled": "False",
        "prefix_cache": "False",
        "stable_diff": "False",
        "base_diff": "False",
        'defensive': {'cutoff': '0.0', 'cutoff_num': '0', 'json': '0.0', 'json_num': '0', 'single': '0.0',
                      'single_num': '0', 'luanma': '0.0', 'luanma_num': '0', 'duolun': '0.0', 'duolun_num': '0',
                      'biaodian': '0.0', 'biaodian_num': '0', 'en_zh': '0.0', 'en_zh_num': '0'}
    }

    if meta_info:
        meta_defaults.update(meta_info)

    payload = {**meta_defaults, **parsed_data}

    print("\n========== 🚀 上传数据预览 ==========")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print(json.dumps(payload, ensure_ascii=False))

    try:
        resp = requests.post(url, json=payload, timeout=30)
        if resp.status_code == 200:
            print("✅ 数据入库成功！")
        else:
            print(f"❌ 入库失败: {resp.status_code}, {resp.text}")
    except Exception as e:
        print(f"❌ 请求异常: {e}")


def main():
    parser = argparse.ArgumentParser(description="Send JSON POST request to fastdeploy_ce")

    parser.add_argument("--url", required=True, help="目标URL")
    parser.add_argument("--paddle_commit_file", default="paddle_commit", help="Paddle commit ID file")
    parser.add_argument("--fd_commit_file", default="fd_commit", help="FD commit ID file")
    parser.add_argument("--benchmark_file", default="benchmark_report.txt", help="benchmark结果文件")
    parser.add_argument("--model", required=True, help="模型信息")
    parser.add_argument("--ipipe", required=True, help="ipipe链接")
    parser.add_argument("--branch", required=True, help="分支")
    parser.add_argument("--deploy_type", default="集中式部署", help="部署方式")
    parser.add_argument("--prefix_cache", default=False, help="是否开启prefix cache")
    parser.add_argument("--log_dir", default="./log", help="FD日志目录")

    args = parser.parse_args()

    model_info = args.model.split("_")

    parsed = parse_benchmark_report(args)
    post_to_fastdeploy_ce(args.url, parsed, meta_info={
        "model": model_info[0],
        "infer_length": model_info[1],
        "infer_type": model_info[2],
        "machine": model_info[3],
        "tp_num": model_info[4],
        "ipipe": args.ipipe,
        "branch": args.branch,
        "deploy_type": args.deploy_type,
        "prefix_cache": args.prefix_cache,
    })


if __name__ == "__main__":
    main()
