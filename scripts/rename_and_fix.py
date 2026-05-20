import os
import re
import zipfile
import shutil
import yaml # 如果沒有安裝，請執行 pip install pyyaml

# 1. 配置路徑與對照表
DESKTOP_PATH = r"D:\Users\yingtsenlin\Desktop\搬運"
TEMP_EXTRACT_DIR = os.path.join(DESKTOP_PATH, "temp_work")

mapping = {
    "cam5202": "apc01", "cam5203": "apc02", "cam6601": "apc03",
    "camCCR01": "apc04", "cam3001": "apc05", "cam1101": "apc06",
    "cam1102": "apc07", "cam1201": "apc08", "cam1202": "apc09",
    "cam1301": "apc10", "cam1302": "apc11", "cam5201": "apc12",
    "cam6101": "apc13"
}

yaml_content = {
    'names': ['person', 'pack', 'helmet', 'mask'],
    'nc': 4,
    'train': '../train/images',
    'val': '../valid/images'
}

def safe_move(src, dst):
    """Move src to dst, renaming if destination already exists."""
    if not os.path.exists(dst):
        shutil.move(src, dst)
        return dst
    base, ext = os.path.splitext(os.path.basename(dst))
    counter = 1
    while True:
        new_dst = os.path.join(os.path.dirname(dst), f"{base}_{counter}{ext}")
        if not os.path.exists(new_dst):
            shutil.move(src, new_dst)
            return new_dst
        counter += 1


def parse_zip_info(filename):
    lower_name = filename.lower()
    if 'grok' in lower_name or 'gemini' in lower_name:
        return filename, None, True
    if not lower_name.endswith('.zip'):
        return None, None, None
    name = filename[:-4]
    m = re.match(r'^(apc_cam\d+_\d{6}_\d+?)_(\d+)$', name, re.IGNORECASE)
    if m:
        return m.group(1), int(m.group(2)), False
    return name, None, False


def merge_cam_suffix_dirs(work_dir):
    """合併 cam 目錄中末尾為 01/02/03 的 images 與 labels。"""
    dirnames = [d for d in os.listdir(work_dir) if os.path.isdir(os.path.join(work_dir, d))]
    groups = {}
    for d in dirnames:
        m = re.match(r'^(cam\d+?)(0[1-3])$', d, re.IGNORECASE)
        if m:
            base = m.group(1)
            groups.setdefault(base, []).append(d)

    for base, dirs in groups.items():
        if len(dirs) > 1:
            print(f"合併 cam 資料夾：{dirs}")
            for d in dirs:
                source_dir = os.path.join(work_dir, d)
                for subfolder in ['images', 'labels']:
                    src_sub = os.path.join(source_dir, subfolder)
                    if os.path.isdir(src_sub):
                        dst_sub = os.path.join(work_dir, subfolder)
                        os.makedirs(dst_sub, exist_ok=True)
                        for item in os.listdir(src_sub):
                            src_item = os.path.join(src_sub, item)
                            dst_item = os.path.join(dst_sub, item)
                            if os.path.exists(dst_item):
                                name, ext = os.path.splitext(item)
                                dst_item = os.path.join(dst_sub, f"{name}_{d}{ext}")
                            shutil.move(src_item, dst_item)
                # 若來源資料夾已空，刪除它
                if not os.listdir(source_dir):
                    os.rmdir(source_dir)


def fix_structure_and_yaml(work_dir):
    """校正資料夾結構並處理 data.yaml"""
    # 檢查是否需要往深一層找 (處理解壓後多出一層資料夾的情況)
    items = os.listdir(work_dir)
    if len(items) == 1 and os.path.isdir(os.path.join(work_dir, items[0])):
        inner_path = os.path.join(work_dir, items[0])
        for f in os.listdir(inner_path):
            safe_move(os.path.join(inner_path, f), os.path.join(work_dir, f))
        shutil.rmtree(inner_path)

    # 如果有多個 cam 開頭並且最後有 01/02/03 的資料夾，先合併它們
    merge_cam_suffix_dirs(work_dir)

    # 確保 images 和 labels 資料夾存在 (即便為空)
    for folder in ['images', 'labels']:
        os.makedirs(os.path.join(work_dir, folder), exist_ok=True)

    # 處理 data.yaml
    yaml_path = os.path.join(work_dir, "data.yaml")
    # 直接覆蓋或新建，確保標籤完全符合要求
    with open(yaml_path, 'w', encoding='utf-8') as f:
        yaml.dump(yaml_content, f, default_flow_style=False)

def merge_chunk_to_root(chunk_dir, root_dir, prefix=None):
    for subfolder in ['images', 'labels']:
        src_sub = os.path.join(chunk_dir, subfolder)
        if not os.path.isdir(src_sub):
            continue
        dst_sub = os.path.join(root_dir, subfolder)
        os.makedirs(dst_sub, exist_ok=True)
        for item in os.listdir(src_sub):
            src_item = os.path.join(src_sub, item)
            if prefix:
                dst_name = f"{prefix}_{item}"
            else:
                dst_name = item
            safe_move(src_item, os.path.join(dst_sub, dst_name))


def process_zips():
    if not os.path.exists(DESKTOP_PATH):
        print(f"錯誤：找不到資料夾 {DESKTOP_PATH}")
        return

    processed_dir = os.path.join(DESKTOP_PATH, "完成上傳檔")
    os.makedirs(processed_dir, exist_ok=True)

    zip_groups = {}
    for filename in sorted(os.listdir(DESKTOP_PATH)):
        if not filename.lower().endswith('.zip'):
            continue
        group_key, chunk_idx, is_special = parse_zip_info(filename)
        if group_key is None:
            continue
        if is_special:
            zip_groups[filename] = [(filename, None, True)]
        else:
            zip_groups.setdefault(group_key, []).append((filename, chunk_idx, False))

    for group_key, entries in zip_groups.items():
        if len(entries) == 1 and entries[0][2]:
            filename = entries[0][0]
            print(f"正在處理: {filename}...")
            new_zip_name = filename
            zip_paths = [(filename, None)]
        else:
            entries = sorted(entries, key=lambda x: (x[1] if x[1] is not None else 0))
            filename = entries[0][0]
            print(f"正在處理群組: {group_key} ({len(entries)} 個 zip)...")
            if group_key.lower().startswith('apc_cam'):
                parts = group_key.split('_')
                cam_id = parts[1]
                if cam_id in mapping:
                    new_zip_name = f"{mapping[cam_id]}_{parts[2]}_{parts[3]}.zip"
                else:
                    print(f"警告：{cam_id} 不在對照表中，保留原始檔名：{filename}")
                    new_zip_name = filename
            else:
                new_zip_name = filename
            zip_paths = [(entry[0], entry[1]) for entry in entries]

        # 檢查並替換 ttc 為 ttcps
        if 'ttc' in new_zip_name.lower():
            new_zip_name = new_zip_name.lower().replace('ttc', 'ttcps')
            print(f"已將 ttc 替換為 ttcps：{new_zip_name}")

        current_temp = os.path.join(TEMP_EXTRACT_DIR, os.path.splitext(group_key)[0])
        if os.path.exists(current_temp):
            shutil.rmtree(current_temp)
        os.makedirs(current_temp, exist_ok=True)

        if len(zip_paths) == 1 and zip_paths[0][1] is None and not zip_paths[0][0].lower().startswith('apc_grok') and not zip_paths[0][0].lower().startswith('apc_gemini'):
            zip_path = os.path.join(DESKTOP_PATH, zip_paths[0][0])
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(current_temp)
            fix_structure_and_yaml(current_temp)
        else:
            for filename, chunk_idx in zip_paths:
                zip_path = os.path.join(DESKTOP_PATH, filename)
                chunk_dir = os.path.join(current_temp, f"chunk_{chunk_idx if chunk_idx is not None else 'single'}")
                os.makedirs(chunk_dir, exist_ok=True)
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(chunk_dir)
                fix_structure_and_yaml(chunk_dir)
                merge_chunk_to_root(chunk_dir, current_temp, prefix=str(chunk_idx) if chunk_idx is not None else None)
                shutil.rmtree(chunk_dir)
            fix_structure_and_yaml(current_temp)

        output_path = os.path.join(processed_dir, new_zip_name)
        if os.path.exists(output_path):
            print(f"警告：輸出檔案已存在，跳過：{new_zip_name}")
            continue
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as new_zip:
            for root, dirs, files in os.walk(current_temp):
                for file in files:
                    file_full_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_full_path, current_temp)
                    new_zip.write(file_full_path, arcname)
        print(f"完成：{new_zip_name}")

    if os.path.exists(TEMP_EXTRACT_DIR):
        shutil.rmtree(TEMP_EXTRACT_DIR)
    print("\n所有檔案處理完畢！請檢查「完成上傳檔」資料夾。")

if __name__ == "__main__":
    process_zips()