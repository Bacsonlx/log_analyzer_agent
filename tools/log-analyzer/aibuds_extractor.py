"""AIBuds 日志提取工具

从原始日志中提取包含 [AIBuds_*] 标签的日志行。
支持按时间范围、模块过滤，以及多文件输入。

可作为 MCP 工具由 server.py 调用，也可通过 CLI 独立运行。
"""

import re
import argparse
import os
import glob
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


class AIBudsLogExtractor:
    def __init__(self, log_file_paths: list[str] | None = None):
        if log_file_paths is None:
            self.log_file_paths = self._find_log_files()
        else:
            self.log_file_paths = (
                log_file_paths if isinstance(log_file_paths, list)
                else [log_file_paths]
            )
        self.aibuds_pattern = re.compile(r'\[AIBuds_\w+\]')
        self.timestamp_patterns = [
            re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})'),
            re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})'),
            re.compile(r'(\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})'),
            re.compile(r'(\d{2}:\d{2}:\d{2}\.\d{3})'),
            re.compile(r'(\d{10}\.\d{3})'),
        ]

    def _find_log_files(self) -> list[str]:
        """自动查找同级目录下的所有日志文件"""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        log_extensions = ['*.log', '*.txt', '*.out']
        log_files: list[str] = []
        for ext in log_extensions:
            log_files.extend(glob.glob(os.path.join(script_dir, ext)))
        if not log_files:
            raise FileNotFoundError("在同级目录下未找到日志文件")
        log_files.sort(key=os.path.getsize, reverse=True)
        return log_files

    def parse_timestamp(self, timestamp_str: str) -> Optional[datetime]:
        """解析时间戳字符串为 datetime 对象"""
        for pattern in self.timestamp_patterns:
            match = pattern.search(timestamp_str)
            if match:
                ts_str = match.group(1)
                try:
                    if '.' in ts_str and len(ts_str.split('.')[0]) == 10:
                        return datetime.fromtimestamp(float(ts_str))
                    elif len(ts_str) == 19:
                        return datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
                    elif len(ts_str) == 23:
                        return datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S.%f')
                    elif len(ts_str) == 12:
                        current_year = datetime.now().year
                        full_ts = f"{current_year}-{ts_str}"
                        return datetime.strptime(full_ts, '%Y-%m-%d %H:%M:%S')
                    elif len(ts_str) == 16:
                        current_year = datetime.now().year
                        full_ts = f"{current_year}-{ts_str}"
                        return datetime.strptime(full_ts, '%Y-%m-%d %H:%M:%S.%f')
                    elif len(ts_str) == 8:
                        today = datetime.now().date()
                        full_ts = f"{today} {ts_str}"
                        return datetime.strptime(full_ts, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    continue
        return None

    def extract_aibuds_logs(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> list[tuple[datetime, str, str]]:
        """提取包含 [AIBuds_*] 的日志，支持多行日志条目和多文件。

        Returns:
            List of (timestamp, log_content, source_filename) tuples.
        """
        start_dt = self.parse_timestamp(start_time) if start_time else None
        end_dt = self.parse_timestamp(end_time) if end_time else None

        all_aibuds_logs: list[tuple[datetime, str, str]] = []

        for log_file_path in self.log_file_paths:
            aibuds_logs: list[tuple[datetime, str, str]] = []
            try:
                with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as file:
                    lines = file.readlines()

                i = 0
                while i < len(lines):
                    line = lines[i].strip()
                    if self.aibuds_pattern.search(line):
                        timestamp = None
                        for pattern in self.timestamp_patterns:
                            if pattern.search(line):
                                timestamp = self.parse_timestamp(line)
                                break
                        if not timestamp:
                            i += 1
                            continue
                        if start_dt and timestamp < start_dt:
                            i += 1
                            continue
                        if end_dt and timestamp > end_dt:
                            i += 1
                            continue

                        log_content = [line]
                        j = i + 1
                        while j < len(lines):
                            next_line = lines[j].strip()
                            has_timestamp = any(
                                p.search(next_line) for p in self.timestamp_patterns
                            )
                            if has_timestamp:
                                break
                            if next_line:
                                log_content.append(next_line)
                            j += 1

                        full_log = '\n'.join(log_content)
                        aibuds_logs.append((
                            timestamp, full_log,
                            os.path.basename(log_file_path),
                        ))
                        i = j
                    else:
                        i += 1
            except FileNotFoundError:
                print(f"错误: 找不到文件 '{log_file_path}'", file=sys.stderr)
                continue
            except Exception as e:
                print(f"错误: 读取 '{log_file_path}' 失败 - {e}", file=sys.stderr)
                continue

            all_aibuds_logs.extend(aibuds_logs)

        return all_aibuds_logs

    def extract_by_module(
        self,
        module_name: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> list[tuple[datetime, str, str]]:
        """提取特定模块的日志"""
        module_pattern = re.compile(rf'\[AIBuds_{module_name}\]')
        start_dt = self.parse_timestamp(start_time) if start_time else None
        end_dt = self.parse_timestamp(end_time) if end_time else None

        all_module_logs: list[tuple[datetime, str, str]] = []

        for log_file_path in self.log_file_paths:
            module_logs: list[tuple[datetime, str, str]] = []
            try:
                with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as file:
                    lines = file.readlines()

                i = 0
                while i < len(lines):
                    line = lines[i].strip()
                    if module_pattern.search(line):
                        timestamp = None
                        for pattern in self.timestamp_patterns:
                            if pattern.search(line):
                                timestamp = self.parse_timestamp(line)
                                break
                        if not timestamp:
                            i += 1
                            continue
                        if start_dt and timestamp < start_dt:
                            i += 1
                            continue
                        if end_dt and timestamp > end_dt:
                            i += 1
                            continue

                        log_content = [line]
                        j = i + 1
                        while j < len(lines):
                            next_line = lines[j].strip()
                            has_timestamp = any(
                                p.search(next_line) for p in self.timestamp_patterns
                            )
                            if has_timestamp:
                                break
                            if next_line:
                                log_content.append(next_line)
                            j += 1

                        full_log = '\n'.join(log_content)
                        module_logs.append((
                            timestamp, full_log,
                            os.path.basename(log_file_path),
                        ))
                        i = j
                    else:
                        i += 1
            except Exception as e:
                print(f"错误: 读取 '{log_file_path}' 失败 - {e}", file=sys.stderr)
                continue

            all_module_logs.extend(module_logs)

        return all_module_logs

    def get_available_modules(self) -> list[str]:
        """获取日志中所有 AIBuds 模块名称"""
        modules: set[str] = set()
        for log_file_path in self.log_file_paths:
            try:
                with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as file:
                    for line in file:
                        matches = self.aibuds_pattern.findall(line)
                        for match in matches:
                            modules.add(match[7:-1])
            except Exception:
                continue
        return sorted(modules)

    def save_logs_to_file(
        self,
        logs: list[tuple[datetime, str, str]],
        output_file: str,
    ) -> None:
        """将提取的日志按时间排序后保存到单个文件"""
        output_dir = os.path.dirname(output_file)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        sorted_logs = sorted(logs, key=lambda x: x[0])
        with open(output_file, 'w', encoding='utf-8') as file:
            for _timestamp, log_line, _source_file in sorted_logs:
                file.write(f"{log_line}\n")


def extract_to_file(
    file_path: str,
    output_dir: str,
    module: str = "",
    start_time: str = "",
    end_time: str = "",
) -> tuple[str, int]:
    """Extract AIBuds logs and save to output directory.

    Returns (output_file_path, extracted_count).
    """
    extractor = AIBudsLogExtractor([file_path])

    if module:
        logs = extractor.extract_by_module(
            module,
            start_time=start_time or None,
            end_time=end_time or None,
        )
    else:
        logs = extractor.extract_aibuds_logs(
            start_time=start_time or None,
            end_time=end_time or None,
        )

    if not logs:
        return "", 0

    os.makedirs(output_dir, exist_ok=True)
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"aiBuds_{module}_" if module else "aiBuds_"
    output_file = os.path.join(output_dir, f"{prefix}{timestamp_str}.log")

    extractor.save_logs_to_file(logs, output_file)
    return output_file, len(logs)


def main():
    parser = argparse.ArgumentParser(
        description='提取包含 [AIBuds_*] 的日志信息'
    )
    parser.add_argument(
        'log_files', nargs='*',
        help='输入的日志文件路径',
    )
    parser.add_argument('-s', '--start', help='开始时间')
    parser.add_argument('-e', '--end', help='结束时间')
    parser.add_argument('-m', '--module', help='指定模块名称')
    parser.add_argument('-o', '--output', help='输出文件路径')
    parser.add_argument(
        '-d', '--output-dir', default='.',
        help='输出目录路径',
    )
    parser.add_argument(
        '--list-modules', action='store_true',
        help='列出所有可用的模块',
    )
    parser.add_argument(
        '--auto', action='store_true',
        help='自动提取并保存',
    )

    args = parser.parse_args()

    try:
        extractor = AIBudsLogExtractor(args.log_files or None)
    except FileNotFoundError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1

    if args.list_modules:
        modules = extractor.get_available_modules()
        print("可用的模块:")
        for m in modules:
            print(f"  - {m}")
        return 0

    if args.module:
        logs = extractor.extract_by_module(args.module, args.start, args.end)
    else:
        logs = extractor.extract_aibuds_logs(args.start, args.end)

    if not logs:
        print("未找到 AIBuds 日志")
        return 0

    if args.output:
        extractor.save_logs_to_file(logs, args.output)
        print(f"已保存 {len(logs)} 条日志到 {args.output}")
    elif args.auto or args.output_dir != '.':
        output_dir = args.output_dir
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = f"aiBuds_{args.module}_" if args.module else "aiBuds_"
        out_path = os.path.join(output_dir, f"{prefix}{ts}.log")
        os.makedirs(output_dir, exist_ok=True)
        extractor.save_logs_to_file(logs, out_path)
        print(f"已保存 {len(logs)} 条日志到 {out_path}")
    else:
        for _ts, log_line, _src in logs:
            print(log_line)

    return 0


if __name__ == "__main__":
    sys.exit(main())
