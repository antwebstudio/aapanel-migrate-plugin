#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import os
import json
import subprocess
import time
import re
import socket
import traceback

# Try importing paramiko for SSH/SFTP testing and folder browsing
try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

def print_result(status, message, data=None):
    print(json.dumps({"status": status, "message": message, "msg": message, "data": data}))
    sys.exit(0)

def log_error(err_type, message):
    try:
        with open("/tmp/ssh_plugin_error.log", "a") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{err_type}] {message}\n")
    except Exception:
        pass

def _get_ssh_host_admin():
    # aaPanel's Terminal module stores saved SSH hosts as AES-encrypted
    # info.json files under config/ssh_info/<host>_<port>/, not in any
    # sqlite table. Reuse the panel's own class so decryption (key from
    # data/a_pass.pl) matches exactly what aaPanel itself uses.
    panel_class = "/www/server/panel/class"
    panel_class_v2 = "/www/server/panel/class_v2"
    if panel_class not in sys.path:
        sys.path.append(panel_class)
    if panel_class_v2 not in sys.path:
        sys.path.append(panel_class_v2)
    import ssh_terminal_v2
    return ssh_terminal_v2.ssh_host_admin()

def load_node_credentials(node_id):
    try:
        ssh_admin = _get_ssh_host_admin()
        info = ssh_admin.get_ssh_info(node_id)
        if not info:
            return None

        host = info.get("host")
        port = info.get("port") or 22
        username = info.get("username") or "root"
        password = info.get("password") or ""
        key = info.get("pkey") or ""

        return {
            "host": host,
            "port": int(port),
            "username": username,
            "password": password,
            "key": key,
            "auth_type": "key" if key else "password"
        }
    except Exception as e:
        log_error("SSH_INFO_LOAD_ERROR", f"Failed to load credentials for node {node_id}: {str(e)}")
        return None

def get_hosts():
    hosts = []
    try:
        ssh_admin = _get_ssh_host_admin()
    except Exception as e:
        log_error("SSH_HOSTS_LOAD_ERROR", f"Failed to load aaPanel ssh_terminal_v2 module: {traceback.format_exc()}")
        print_result(False, f"Could not read aaPanel's saved SSH hosts: {str(e)}")
        return

    save_path = ssh_admin._save_path
    if not os.path.exists(save_path):
        print_result(True, "Success", hosts)
        return

    for name in sorted(os.listdir(save_path)):
        info_file = os.path.join(save_path, name, "info.json")
        if not os.path.exists(info_file):
            continue
        try:
            info = ssh_admin.get_ssh_info(name)
        except Exception as e:
            log_error("SSH_INFO_DECODE_ERROR", f"Failed to decrypt saved SSH host '{name}': {traceback.format_exc()}")
            continue
        if not info:
            continue

        host_ip = info.get("host")
        port = info.get("port") or 22
        user = info.get("username") or "root"
        remark = info.get("ps") or f"{user}@{host_ip}"

        hosts.append({
            "id": name,
            "host": host_ip,
            "port": int(port),
            "username": user,
            "remark": remark,
            "has_password": bool(info.get("password")),
            "has_key": bool(info.get("pkey"))
        })

    print_result(True, "Success", hosts)

def get_sites():
    db_paths = [
        "/www/server/panel/data/default.db",
        "/www/server/panel/data/db/panel.db",
        "/www/server/panel/data/panel.db"
    ]
    sites = []
    import sqlite3
    
    for path in db_paths:
        if os.path.exists(path):
            if not os.access(path, os.R_OK):
                continue
            try:
                conn = sqlite3.connect(path)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sites'")
                if cursor.fetchone():
                    cursor.execute("PRAGMA table_info(sites)")
                    columns = [c[1] for c in cursor.fetchall()]
                    
                    cursor.execute("SELECT * FROM sites")
                    rows = cursor.fetchall()
                    for row in rows:
                        site = {}
                        for i, col in enumerate(columns):
                            site[col] = row[i]
                        
                        sites.append({
                            "id": site.get("id") or site.get("ID"),
                            "name": site.get("name"),
                            "path": site.get("path")
                        })
                    conn.close()
                    break
                conn.close()
            except Exception as e:
                log_error("SITES_READ_ERROR", f"Exception while reading websites from {path}: {str(e)}")

    print_result(True, "Success", sites)

def test_ssh(config):
    node_id = config.get("node_id")
    if node_id:
        creds = load_node_credentials(node_id)
        if not creds:
            print_result(False, f"Node ID {node_id} not found in hosts database.")
        config.update(creds)

    host = config.get("host")
    port = int(config.get("port", 22))
    username = config.get("username", "root")
    auth_type = config.get("auth_type", "password")
    password = config.get("password", "")
    key_content = config.get("key", "")

    # Quick socket check first
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect((host, port))
        sock.close()
    except Exception as e:
        print_result(False, f"Port check failed: Host {host}:{port} is unreachable. Error: {str(e)}")

    if not HAS_PARAMIKO:
        return test_ssh_shell(host, port, username, auth_type, password, key_content)

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        if auth_type == "key" and key_content:
            from io import StringIO
            key_file = StringIO(key_content)
            try:
                pkey = paramiko.RSAKey.from_private_key(key_file)
            except Exception:
                try:
                    key_file.seek(0)
                    pkey = paramiko.Ed25519Key.from_private_key(key_file)
                except Exception as e:
                    print_result(False, f"Failed to parse private key: {str(e)}")
            ssh.connect(host, port=port, username=username, pkey=pkey, timeout=5)
        else:
            ssh.connect(host, port=port, username=username, password=password, timeout=5)
        
        ssh.close()
        print_result(True, "SSH Connection Successful!")
    except Exception as e:
        print_result(False, f"SSH Authentication Failed: {str(e)}")

def test_ssh_shell(host, port, username, auth_type, password, key_content):
    if auth_type == "key" and key_content:
        key_path = "/tmp/test_ssh_key_" + str(int(time.time()))
        with open(key_path, "w") as f:
            f.write(key_content)
        os.chmod(key_path, 0o600)
        cmd = f"ssh -i {key_path} -p {port} -o StrictHostKeyChecking=no -o ConnectTimeout=5 {username}@{host} 'echo success'"
    else:
        cmd = f"ssh -p {port} -o StrictHostKeyChecking=no -o ConnectTimeout=5 {username}@{host} 'echo success'"
        if subprocess.call("which sshpass", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) == 0:
            cmd = f"sshpass -p '{password}' " + cmd
        else:
            print_result(True, "Port is open, but authentication check requires sshpass or paramiko library.")
            return

    try:
        p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate()
        if auth_type == "key" and os.path.exists(key_path):
            os.remove(key_path)
        
        if p.returncode == 0:
            print_result(True, "SSH Connection Successful!")
        else:
            print_result(False, f"Connection failed: {err.decode('utf-8', 'ignore').strip()}")
    except Exception as e:
        print_result(False, f"Failed to test connection: {str(e)}")

def list_remote_dir(config):
    node_id = config.get("node_id")
    if node_id:
        creds = load_node_credentials(node_id)
        if not creds:
            print_result(False, f"Node ID {node_id} not found.")
        config.update(creds)

    host = config.get("host")
    port = int(config.get("port", 22))
    username = config.get("username", "root")
    auth_type = config.get("auth_type", "password")
    password = config.get("password", "")
    key_content = config.get("key", "")
    path = config.get("path", "/")

    if not HAS_PARAMIKO:
        return list_remote_dir_shell(host, port, username, auth_type, password, key_content, path)

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if auth_type == "key" and key_content:
            from io import StringIO
            key_file = StringIO(key_content)
            try:
                pkey = paramiko.RSAKey.from_private_key(key_file)
            except Exception:
                key_file.seek(0)
                pkey = paramiko.Ed25519Key.from_private_key(key_file)
            ssh.connect(host, port=port, username=username, pkey=pkey, timeout=5)
        else:
            ssh.connect(host, port=port, username=username, password=password, timeout=5)
        
        sftp = ssh.open_sftp()
        try:
            files = sftp.listdir_attr(path)
            result = []
            for f in files:
                is_dir = (f.st_mode & 0o170000) == 0o040000
                result.append({
                    "name": f.filename,
                    "is_dir": is_dir,
                    "size": f.st_size,
                    "mtime": f.st_mtime
                })
            sftp.close()
            ssh.close()
            print_result(True, "Success", result)
        except Exception as e:
            print_result(False, f"Failed to read directory {path}: {str(e)}")
    except Exception as e:
        print_result(False, f"SSH Connection Failed: {str(e)}")

def list_remote_dir_shell(host, port, username, auth_type, password, key_content, path):
    cmd = f"ls -p {path}"
    if auth_type == "key" and key_content:
        key_path = "/tmp/list_ssh_key_" + str(int(time.time()))
        with open(key_path, "w") as f:
            f.write(key_content)
        os.chmod(key_path, 0o600)
        ssh_cmd = f"ssh -i {key_path} -p {port} -o StrictHostKeyChecking=no {username}@{host} '{cmd}'"
    else:
        ssh_cmd = f"ssh -p {port} -o StrictHostKeyChecking=no {username}@{host} '{cmd}'"
        if subprocess.call("which sshpass", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) == 0:
            ssh_cmd = f"sshpass -p '{password}' " + ssh_cmd
        else:
            print_result(False, "Listing directories requires 'paramiko' or 'sshpass' installed.")
            return

    try:
        p = subprocess.Popen(ssh_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate()
        if auth_type == "key" and os.path.exists(key_path):
            os.remove(key_path)
        
        if p.returncode == 0:
            lines = out.decode("utf-8", "ignore").strip().split("\n")
            result = []
            for line in lines:
                if not line: continue
                is_dir = line.endswith("/")
                name = line[:-1] if is_dir else line
                result.append({
                    "name": name,
                    "is_dir": is_dir,
                    "size": 0,
                    "mtime": int(time.time())
                })
            print_result(True, "Success", result)
        else:
            print_result(False, f"Failed: {err.decode('utf-8', 'ignore').strip()}")
    except Exception as e:
        print_result(False, f"Failed to list directory: {str(e)}")

def get_local_mysql_root():
    # 1. Try /www/server/panel/data/mysql-root.pl
    root_pl_path = "/www/server/panel/data/mysql-root.pl"
    if os.path.exists(root_pl_path):
        try:
            with open(root_pl_path, "r") as f:
                pwd = f.read().strip()
                if pwd:
                    return pwd
        except Exception:
            pass

    # 2. Try SQLite
    db_paths = [
        "/www/server/panel/data/default.db",
        "/www/server/panel/data/db/panel.db",
        "/www/server/panel/data/panel.db"
    ]
    for path in db_paths:
        if os.path.exists(path):
            try:
                import sqlite3
                conn = sqlite3.connect(path)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='config'")
                if cursor.fetchone():
                    cursor.execute("SELECT mysql_root FROM config LIMIT 1")
                    row = cursor.fetchone()
                    if row and row[0]:
                        pwd = row[0].strip()
                        conn.close()
                        return pwd
                conn.close()
            except Exception:
                pass
    
    # 3. Development / Laragon fallback (empty on Windows Laragon usually)
    return ""

def run_remote_ssh_command(config, command):
    host = config.get("host")
    port = int(config.get("port", 22))
    username = config.get("username", "root")
    auth_type = config.get("auth_type", "password")
    password = config.get("password", "")
    key_content = config.get("key", "")

    if HAS_PARAMIKO:
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            if auth_type == "key" and key_content:
                from io import StringIO
                key_file = StringIO(key_content)
                try:
                    pkey = paramiko.RSAKey.from_private_key(key_file)
                except Exception:
                    key_file.seek(0)
                    pkey = paramiko.Ed25519Key.from_private_key(key_file)
                ssh.connect(host, port=port, username=username, pkey=pkey, timeout=10)
            else:
                ssh.connect(host, port=port, username=username, password=password, timeout=10)
            
            stdin, stdout, stderr = ssh.exec_command(command)
            out_val = stdout.read().decode('utf-8', 'ignore')
            err_val = stderr.read().decode('utf-8', 'ignore')
            exit_status = stdout.channel.recv_exit_status()
            ssh.close()
            return exit_status == 0, out_val, err_val
        except Exception as e:
            return False, "", str(e)
    else:
        # Fallback to shell SSH
        tmp_base = "C:/Windows/Temp" if sys.platform.startswith('win') else "/tmp"
        if not os.path.exists(tmp_base):
            tmp_base = "."
        
        key_path = None
        if auth_type == "key" and key_content:
            key_path = os.path.join(tmp_base, f"cmd_key_{int(time.time())}")
            with open(key_path, "w") as f:
                f.write(key_content)
            os.chmod(key_path, 0o600)
            ssh_cmd = f"ssh -i {key_path} -p {port} -o StrictHostKeyChecking=no {username}@{host} '{command}'"
        else:
            ssh_cmd = f"ssh -p {port} -o StrictHostKeyChecking=no {username}@{host} '{command}'"
            use_sshpass = subprocess.call("which sshpass", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) == 0
            if use_sshpass:
                ssh_cmd = f"sshpass -p '{password}' " + ssh_cmd
        
        try:
            p = subprocess.Popen(ssh_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = p.communicate()
            if key_path and os.path.exists(key_path):
                os.remove(key_path)
            return p.returncode == 0, out.decode('utf-8', 'ignore'), err.decode('utf-8', 'ignore')
        except Exception as e:
            if key_path and os.path.exists(key_path):
                os.remove(key_path)
            return False, "", str(e)

def download_remote_file(config, remote_file, local_file):
    host = config.get("host")
    port = int(config.get("port", 22))
    username = config.get("username", "root")
    auth_type = config.get("auth_type", "password")
    password = config.get("password", "")
    key_content = config.get("key", "")

    if HAS_PARAMIKO:
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            if auth_type == "key" and key_content:
                from io import StringIO
                key_file = StringIO(key_content)
                try:
                    pkey = paramiko.RSAKey.from_private_key(key_file)
                except Exception:
                    key_file.seek(0)
                    pkey = paramiko.Ed25519Key.from_private_key(key_file)
                ssh.connect(host, port=port, username=username, pkey=pkey, timeout=10)
            else:
                ssh.connect(host, port=port, username=username, password=password, timeout=10)
            
            sftp = ssh.open_sftp()
            sftp.get(remote_file, local_file)
            sftp.close()
            ssh.close()
            return True, ""
        except Exception as e:
            return False, str(e)
    else:
        # Fallback to scp
        tmp_base = "C:/Windows/Temp" if sys.platform.startswith('win') else "/tmp"
        if not os.path.exists(tmp_base):
            tmp_base = "."
        
        key_path = None
        if auth_type == "key" and key_content:
            key_path = os.path.join(tmp_base, f"scp_key_{int(time.time())}")
            with open(key_path, "w") as f:
                f.write(key_content)
            os.chmod(key_path, 0o600)
            scp_cmd = f"scp -i {key_path} -P {port} -o StrictHostKeyChecking=no {username}@{host}:{remote_file} {local_file}"
        else:
            scp_cmd = f"scp -P {port} -o StrictHostKeyChecking=no {username}@{host}:{remote_file} {local_file}"
            use_sshpass = subprocess.call("which sshpass", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) == 0
            if use_sshpass:
                scp_cmd = f"sshpass -p '{password}' " + scp_cmd
        
        try:
            p = subprocess.Popen(scp_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = p.communicate()
            if key_path and os.path.exists(key_path):
                os.remove(key_path)
            if p.returncode == 0:
                return True, ""
            else:
                return False, err.decode('utf-8', 'ignore')
        except Exception as e:
            if key_path and os.path.exists(key_path):
                os.remove(key_path)
            return False, str(e)

def run_local_mysql_query(queries, root_password):
    if root_password:
        cmd = ["mysql", "-uroot", f"-p{root_password}", "-e", queries]
    else:
        cmd = ["mysql", "-uroot", "-e", queries]
    
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate()
        return p.returncode == 0, out, err
    except Exception as e:
        return False, b"", str(e).encode('utf-8')

def import_local_sql_dump(db_name, root_password, dump_path):
    if root_password:
        cmd = ["mysql", "-uroot", f"-p{root_password}", db_name]
    else:
        cmd = ["mysql", "-uroot", db_name]
    
    try:
        with open(dump_path, "rb") as f:
            p = subprocess.Popen(cmd, stdin=f, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = p.communicate()
            return p.returncode == 0, out, err
    except Exception as e:
        return False, b"", str(e).encode('utf-8')

def register_database_in_aapanel(db_name, db_user, db_password):
    db_paths = [
        "/www/server/panel/data/default.db",
        "/www/server/panel/data/db/panel.db",
        "/www/server/panel/data/panel.db"
    ]
    for path in db_paths:
        if os.path.exists(path):
            try:
                import sqlite3
                conn = sqlite3.connect(path)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='databases'")
                if cursor.fetchone():
                    cursor.execute("SELECT id FROM databases WHERE name = ?", (db_name,))
                    if not cursor.fetchone():
                        addtime = time.strftime('%Y-%m-%d %H:%M:%S')
                        cursor.execute(
                            "INSERT INTO databases (name, username, password, accept, ps, addtime) VALUES (?, ?, ?, ?, ?, ?)",
                            (db_name, db_user, db_password, '127.0.0.1', 'Migrated via SSH Plugin', addtime)
                        )
                        conn.commit()
                conn.close()
                return True
            except Exception as e:
                log_error("SQLITE_REGISTER_ERROR", f"Failed to register db {db_name} in {path}: {str(e)}")
    return False

def extract_wp_define(content, name):
    m = re.search(r"define\s*\(\s*['\"]" + re.escape(name) + r"['\"]\s*,\s*['\"](.*?)['\"]\s*\)", content, re.DOTALL)
    return m.group(1) if m else ""

def migrate_database(config, log_file, update_status):
    db_migrate = config.get("db_migrate")
    if not db_migrate or str(db_migrate) != "1":
        return True, "No database migration requested."

    with open(log_file, "a") as lf:
        lf.write("\n=========================================\n")
        lf.write("Starting Database Migration...\n")
        lf.flush()

    db_source_mode = config.get("db_source_mode", "env")
    db_host = "127.0.0.1"
    db_port = "3306"
    db_name = ""
    db_user = ""
    db_password = ""

    if db_source_mode == "env":
        db_env_path = config.get("db_env_path", "")
        if not db_env_path:
            with open(log_file, "a") as lf:
                lf.write("Error: Remote .env file path is not specified.\n")
            return False, "Remote .env file path is not specified."
        
        with open(log_file, "a") as lf:
            lf.write(f"Reading remote .env file at: {db_env_path}\n")
            lf.flush()
        
        status, out, err = run_remote_ssh_command(config, f"cat '{db_env_path}'")
        if not status:
            with open(log_file, "a") as lf:
                lf.write(f"Error reading remote .env file: {err}\n")
            return False, f"Failed to read remote .env: {err}"
        
        env_vars = {}
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, val = line.split('=', 1)
                key = key.strip()
                val = val.strip()
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                env_vars[key] = val
        
        db_host = env_vars.get("DB_HOST", "127.0.0.1")
        db_port = env_vars.get("DB_PORT", "3306")
        db_name = env_vars.get("DB_DATABASE") or env_vars.get("DB_NAME") or env_vars.get("MYSQL_DATABASE")
        db_user = env_vars.get("DB_USERNAME") or env_vars.get("DB_USER") or env_vars.get("MYSQL_USER")
        db_password = env_vars.get("DB_PASSWORD") or env_vars.get("DB_PASS") or env_vars.get("MYSQL_PASSWORD") or ""

        if not db_name or not db_user:
            with open(log_file, "a") as lf:
                lf.write(f"Error parsing .env file. Environment variables: {list(env_vars.keys())}\n")
            return False, "Failed to parse database name or user from remote .env file."
        
        with open(log_file, "a") as lf:
            lf.write(f"Parsed credentials for database: {db_name}\n")
            lf.flush()
    elif db_source_mode == "wp_config":
        db_wp_config_path = config.get("db_wp_config_path", "")
        if not db_wp_config_path:
            with open(log_file, "a") as lf:
                lf.write("Error: Remote wp-config.php path is not specified.\n")
            return False, "Remote wp-config.php path is not specified."

        with open(log_file, "a") as lf:
            lf.write(f"Reading remote wp-config.php file at: {db_wp_config_path}\n")
            lf.flush()

        status, out, err = run_remote_ssh_command(config, f"cat '{db_wp_config_path}'")
        if not status:
            with open(log_file, "a") as lf:
                lf.write(f"Error reading remote wp-config.php file: {err}\n")
            return False, f"Failed to read remote wp-config.php: {err}"

        db_name = extract_wp_define(out, "DB_NAME")
        db_user = extract_wp_define(out, "DB_USER")
        db_password = extract_wp_define(out, "DB_PASSWORD")
        db_host_raw = extract_wp_define(out, "DB_HOST") or "localhost"
        if ":" in db_host_raw:
            host_part, port_part = db_host_raw.split(":", 1)
            db_host = host_part
            db_port = port_part if port_part.isdigit() else "3306"
        else:
            db_host = db_host_raw
            db_port = "3306"

        if not db_name or not db_user:
            with open(log_file, "a") as lf:
                lf.write("Error parsing wp-config.php -- could not find DB_NAME/DB_USER constants. Is this a valid WordPress config file?\n")
            return False, "Could not find WordPress database constants (DB_NAME/DB_USER) in the remote wp-config.php."

        with open(log_file, "a") as lf:
            lf.write(f"Parsed WordPress database credentials for database: {db_name}\n")
            lf.flush()
    else:
        db_host = config.get("db_host", "127.0.0.1")
        db_port = config.get("db_port", "3306")
        db_name = config.get("db_name", "")
        db_user = config.get("db_user", "")
        db_password = config.get("db_password", "")

    with open(log_file, "a") as lf:
        lf.write(f"Source Database Host: {db_host}:{db_port}\n")
        lf.write(f"Source Database Name: {db_name}\n")
        lf.write(f"Source Database User: {db_user}\n")
        lf.write("Exporting remote database using mysqldump...\n")
        lf.flush()

    task_id = config.get("task_id", str(int(time.time())))
    remote_sql_path = f"/tmp/db_migrate_{task_id}.sql"
    
    tmp_base = "C:/Windows/Temp" if sys.platform.startswith('win') else "/tmp"
    if not os.path.exists(tmp_base):
        tmp_base = "."
    local_sql_path = os.path.join(tmp_base, f"db_migrate_{task_id}.sql")

    db_password_escaped = db_password.replace("'", "'\\''")
    dump_cmd = f"mysqldump -h '{db_host}' -P '{db_port}' -u '{db_user}' -p'{db_password_escaped}' '{db_name}' > '{remote_sql_path}'"
    status, out, err = run_remote_ssh_command(config, dump_cmd)
    if not status:
        with open(log_file, "a") as lf:
            lf.write(f"Error running remote mysqldump: {err}\n")
        return False, f"Remote mysqldump failed: {err}"

    with open(log_file, "a") as lf:
        lf.write("Remote database exported successfully. Downloading SQL file to local...\n")
        lf.flush()

    dl_status, dl_err = download_remote_file(config, remote_sql_path, local_sql_path)
    if not dl_status:
        with open(log_file, "a") as lf:
            lf.write(f"Error downloading SQL file: {dl_err}\n")
        run_remote_ssh_command(config, f"rm -f '{remote_sql_path}'")
        return False, f"Failed to download SQL dump: {dl_err}"

    with open(log_file, "a") as lf:
        lf.write("SQL file downloaded successfully. Setting up local database and users...\n")
        lf.flush()

    root_pwd = get_local_mysql_root()
    sql_queries = (
        f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n"
        f"CREATE USER IF NOT EXISTS '{db_user}'@'localhost' IDENTIFIED BY '{db_password}';\n"
        f"ALTER USER '{db_user}'@'localhost' IDENTIFIED BY '{db_password}';\n"
        f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'localhost';\n"
        f"CREATE USER IF NOT EXISTS '{db_user}'@'127.0.0.1' IDENTIFIED BY '{db_password}';\n"
        f"ALTER USER '{db_user}'@'127.0.0.1' IDENTIFIED BY '{db_password}';\n"
        f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'127.0.0.1';\n"
        f"CREATE USER IF NOT EXISTS '{db_user}'@'%' IDENTIFIED BY '{db_password}';\n"
        f"ALTER USER '{db_user}'@'%' IDENTIFIED BY '{db_password}';\n"
        f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'%';\n"
        f"FLUSH PRIVILEGES;"
    )

    db_status, db_out, db_err = run_local_mysql_query(sql_queries, root_pwd)
    if not db_status:
        with open(log_file, "a") as lf:
            lf.write(f"Error creating local database/user: {db_err.decode('utf-8', 'ignore')}\n")
        run_remote_ssh_command(config, f"rm -f '{remote_sql_path}'")
        if os.path.exists(local_sql_path):
            os.remove(local_sql_path)
        return False, f"Failed to create local database/user: {db_err.decode('utf-8', 'ignore')}"

    with open(log_file, "a") as lf:
        lf.write("Local database and user configured. Importing SQL dump...\n")
        lf.flush()

    imp_status, imp_out, imp_err = import_local_sql_dump(db_name, root_pwd, local_sql_path)
    if not imp_status:
        with open(log_file, "a") as lf:
            lf.write(f"Error importing SQL dump: {imp_err.decode('utf-8', 'ignore')}\n")
        run_remote_ssh_command(config, f"rm -f '{remote_sql_path}'")
        if os.path.exists(local_sql_path):
            os.remove(local_sql_path)
        return False, f"Failed to import local SQL: {imp_err.decode('utf-8', 'ignore')}"

    with open(log_file, "a") as lf:
        lf.write("SQL dump imported successfully! Registering database in aaPanel...\n")
        lf.flush()

    register_database_in_aapanel(db_name, db_user, db_password)

    run_remote_ssh_command(config, f"rm -f '{remote_sql_path}'")
    if os.path.exists(local_sql_path):
        os.remove(local_sql_path)

    with open(log_file, "a") as lf:
        lf.write("Database Migration Completed Successfully!\n")
        lf.write("=========================================\n\n")
        lf.flush()

    return True, "Database migrated successfully."

def run_copy(config):
    node_id = config.get("node_id")
    if node_id:
        creds = load_node_credentials(node_id)
        if not creds:
            print_result(False, f"Node ID {node_id} not found.")
        config.update(creds)

    host = config.get("host")
    port = int(config.get("port", 22))
    username = config.get("username", "root")
    auth_type = config.get("auth_type", "password")
    password = config.get("password", "")
    key_content = config.get("key", "")
    remote_dir = config.get("remote_dir", "")
    local_dir = config.get("local_dir", "")
    exclude_folders = config.get("exclude_folders", "")
    sync_mode = config.get("sync_mode", False)
    overwrite = config.get("overwrite", True)
    task_id = config.get("task_id", str(int(time.time())))
    
    tmp_base = "C:/Windows/Temp" if sys.platform.startswith('win') else "/tmp"
    if not os.path.exists(tmp_base):
        tmp_base = "."
        
    status_file = os.path.join(tmp_base, f"copy_status_{task_id}.json")
    log_file = os.path.join(tmp_base, f"copy_log_{task_id}.log")

    def update_status(progress=0, speed="", eta="", status="running", error=""):
        with open(status_file, "w") as sf:
            json.dump({
                "progress": progress,
                "speed": speed,
                "eta": eta,
                "status": status,
                "error": error,
                "updated_at": int(time.time())
            }, sf)

    db_only = config.get("db_only")
    is_db_only = db_only and (str(db_only) == "1" or db_only is True)

    if not is_db_only:
        if not os.path.exists(local_dir):
            try:
                os.makedirs(local_dir, 0o755)
            except Exception as e:
                update_status(0, "", "", "error", f"Failed to create local directory: {str(e)}")
                with open(log_file, "a") as lf:
                    lf.write(f"Error: Failed to create local directory: {str(e)}\n")
                print_result(False, f"Failed to create local directory: {str(e)}")

    # Core database migration hook execution
    db_success, db_msg = migrate_database(config, log_file, update_status)
    if not db_success:
        update_status(0, "", "", "error", f"Database Migration Failed: {db_msg}")
        print_result(False, f"Database Migration Failed: {db_msg}")

    # If database only migration, finish the task cleanly here
    if is_db_only:
        update_status(100, "", "", "success")
        print_result(True, "Database Migration Completed Successfully!")

    rsync_cmd = ["rsync", "-avz", "--progress"]
    
    if sync_mode:
        rsync_cmd.append("--delete")
    
    if not overwrite:
        rsync_cmd.append("--ignore-existing")

    if exclude_folders:
        parts = [p.strip() for p in exclude_folders.split(",") if p.strip()]
        for p in parts:
            rsync_cmd.append(f"--exclude={p}")

    # Always exclude .user.ini to avoid unlinking errors due to chattr +i permissions on Linux
    rsync_cmd.append("--exclude=.user.ini")

    key_path = None
    if auth_type == "key" and key_content:
        key_path = os.path.join(tmp_base, f"copy_key_{task_id}")
        with open(key_path, "w") as f:
            f.write(key_content)
        os.chmod(key_path, 0o600)
        rsync_cmd.extend(["-e", f"ssh -i {key_path} -p {port} -o StrictHostKeyChecking=no"])
    else:
        rsync_cmd.extend(["-e", f"ssh -p {port} -o StrictHostKeyChecking=no"])

    rsync_cmd.append(f"{username}@{host}:{remote_dir}/")
    rsync_cmd.append(local_dir)

    use_sshpass = False
    if auth_type == "password":
        if subprocess.call("which sshpass", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) == 0:
            use_sshpass = True
        else:
            with open(log_file, "a") as lf:
                lf.write("sshpass not found, attempting auto-installation...\n")
            subprocess.call("yum install -y sshpass || apt-get install -y sshpass", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if subprocess.call("which sshpass", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) == 0:
                use_sshpass = True
            else:
                with open(log_file, "a") as lf:
                    lf.write("Auto-installation of sshpass failed. Retrying transfer without sshpass...\n")

    final_cmd = rsync_cmd
    if auth_type == "password" and use_sshpass:
        final_cmd = ["sshpass", "-p", password] + rsync_cmd

    try:
        with open(log_file, "w") as log_out:
            log_out.write(f"Copy task started at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            log_out.write(f"Command: {' '.join(final_cmd).replace(password, '******') if password else ' '.join(final_cmd)}\n\n")
            log_out.flush()

            p = subprocess.Popen(final_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, close_fds=True, bufsize=1, universal_newlines=True)

            current_progress = 0
            current_speed = ""
            current_eta = ""

            for line in p.stdout:
                log_out.write(line)
                log_out.flush()

                progress_match = re.search(r'(\d+)%\s+([\d\.]+[a-zA-Z]+/s)\s+(\d+:\d+:\d+)', line)
                if progress_match:
                    pct = int(progress_match.group(1))
                    speed = progress_match.group(2)
                    eta = progress_match.group(3)
                    
                    if pct > current_progress:
                        current_progress = pct
                    current_speed = speed
                    current_eta = eta
                    update_status(current_progress, current_speed, current_eta, "running")

            p.wait()

            if key_path and os.path.exists(key_path):
                os.remove(key_path)

            if p.returncode == 0:
                log_out.write(f"\nCopy task completed successfully at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                update_status(100, "", "", "success")
                print_result(True, "Copy Completed Successfully!")
            else:
                log_out.write(f"\nCopy task failed with exit code {p.returncode}\n")
                update_status(current_progress, "", "", "error", f"Transfer failed with exit status {p.returncode}.")
                print_result(False, f"Copy process failed. Exit code: {p.returncode}")
                
    except Exception as e:
        if key_path and os.path.exists(key_path):
            os.remove(key_path)
        update_status(0, "", "", "error", str(e))
        with open(log_file, "a") as lf:
            lf.write(f"\nCritical Exception: {str(e)}\n")
        print_result(False, f"Error: {str(e)}")

if __name__ == "__main__":
    try:
        input_data = sys.stdin.read()
        config = json.loads(input_data)
    except Exception as e:
        print_result(False, f"Invalid JSON config input: {str(e)}")

    action = config.get("action", "test")
    if action == "hosts":
        get_hosts()
    elif action == "sites":
        get_sites()
    elif action == "test":
        test_ssh(config)
    elif action == "list":
        list_remote_dir(config)
    elif action == "copy":
        run_copy(config)
    else:
        print_result(False, f"Unknown action: {action}")
