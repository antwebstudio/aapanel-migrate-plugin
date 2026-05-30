#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import os
import json
import subprocess
import time
import re
import socket

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

def load_node_credentials(node_id):
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
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='hosts'")
                if cursor.fetchone():
                    cursor.execute("PRAGMA table_info(hosts)")
                    columns = [c[1] for c in cursor.fetchall()]
                    id_col = "id"
                    for col in columns:
                        if col.lower() == "id":
                            id_col = col
                            break
                    cursor.execute(f"SELECT * FROM hosts WHERE {id_col} = {int(node_id)}")
                    row = cursor.fetchone()
                    if row:
                        node = {}
                        for i, col in enumerate(columns):
                            node[col] = row[i]
                        conn.close()
                        
                        host = node.get("host")
                        port = node.get("port") or 22
                        username = node.get("username") or node.get("user") or "root"
                        password = node.get("password") or node.get("pass") or ""
                        key = node.get("key") or node.get("pkey") or node.get("private_key") or ""
                        
                        if (password and password.startswith("BT-0x")) or (key and key.startswith("BT-0x")):
                            try:
                                sys.path.append('/www/server/panel/class')
                                import public
                                if password and password.startswith("BT-0x"):
                                    password = public.rsa_decrypt(password)
                                if key and key.startswith("BT-0x"):
                                    key = public.rsa_decrypt(key)
                            except Exception as ex:
                                log_error("DECRYPTION_ERROR", f"Failed to decrypt credentials for node {node_id}: {str(ex)}")
                                
                        auth_type = "key" if key else "password"
                        return {
                            "host": host,
                            "port": int(port),
                            "username": username,
                            "password": password,
                            "key": key,
                            "auth_type": auth_type
                        }
                conn.close()
            except Exception as e:
                log_error("DB_LOAD_ERROR", f"Failed to load credentials from {path} for node {node_id}: {str(e)}")
    return None

def get_hosts():
    db_paths = [
        "/www/server/panel/data/default.db",
        "/www/server/panel/data/db/panel.db",
        "/www/server/panel/data/panel.db"
    ]
    hosts = []
    import sqlite3
    
    for path in db_paths:
        if os.path.exists(path):
            if not os.access(path, os.R_OK):
                log_error("PERMISSION_DENIED", f"Database file {path} exists but is not readable.")
                continue
            try:
                conn = sqlite3.connect(path)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='hosts'")
                if cursor.fetchone():
                    cursor.execute("PRAGMA table_info(hosts)")
                    columns = [c[1] for c in cursor.fetchall()]
                    
                    cursor.execute("SELECT * FROM hosts")
                    rows = cursor.fetchall()
                    for row in rows:
                        node = {}
                        for i, col in enumerate(columns):
                            node[col] = row[i]
                        
                        node_id = node.get("id") or node.get("ID")
                        host_ip = node.get("host")
                        port = node.get("port") or 22
                        user = node.get("username") or node.get("user") or "root"
                        remark = node.get("remark") or node.get("name") or node.get("alias") or f"{user}@{host_ip}"
                        
                        has_password = bool(node.get("password") or node.get("pass"))
                        has_key = bool(node.get("key") or node.get("pkey") or node.get("private_key"))
                        
                        hosts.append({
                            "id": node_id,
                            "host": host_ip,
                            "port": int(port),
                            "username": user,
                            "remark": remark,
                            "has_password": has_password,
                            "has_key": has_key
                        })
                    conn.close()
                    break
                conn.close()
            except Exception as e:
                log_error("DB_READ_ERROR", f"Exception while reading database {path}: {str(e)}")
        
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
    
    tmp_base = os.path.dirname(os.path.abspath(__file__))
        
    status_file = os.path.join(tmp_base, f"copy_status_{task_id}.json")
    log_file = os.path.join(tmp_base, f"copy_log_{task_id}.log")

    def update_status(progress=0, speed="", eta="", status="running", error=""):
        tmp_status = status_file + ".tmp"
        try:
            with open(tmp_status, "w") as sf:
                json.dump({
                    "progress": progress,
                    "speed": speed,
                    "eta": eta,
                    "status": status,
                    "error": error,
                    "updated_at": int(time.time())
                }, sf)
            os.replace(tmp_status, status_file)
        except Exception:
            try:
                with open(status_file, "w") as sf:
                    json.dump({
                        "progress": progress,
                        "speed": speed,
                        "eta": eta,
                        "status": status,
                        "error": error,
                        "updated_at": int(time.time())
                    }, sf)
            except Exception:
                pass

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

    # Check if local rsync supports --info=progress2 (rsync 3.1.0+)
    supports_progress2 = False
    try:
        p_check = subprocess.Popen(["rsync", "--info=help"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        out_check, _ = p_check.communicate()
        if "progress2" in out_check:
            supports_progress2 = True
    except Exception:
        pass

    # Check if stdbuf is available (to prevent rsync pipe buffering issues)
    has_stdbuf = False
    try:
        p_check = subprocess.Popen(["stdbuf", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        p_check.communicate()
        if p_check.returncode == 0:
            has_stdbuf = True
    except Exception:
        pass

    rsync_cmd = []
    if has_stdbuf:
        rsync_cmd.extend(["stdbuf", "-oL"])
    
    rsync_cmd.extend(["rsync", "-avz"])
    if supports_progress2:
        rsync_cmd.append("--info=progress2")
    else:
        rsync_cmd.append("--progress")
    
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
            last_total = 0
            last_remaining = 0

            for line in p.stdout:
                progress_match = re.search(r'(\d+)%\s+([\d\.]+[a-zA-Z]+/s)\s+(\d+:\d+(?::\d+)?)', line)
                if progress_match:
                    pct = int(progress_match.group(1))
                    speed = progress_match.group(2)
                    eta = progress_match.group(3)
                    
                    raw_pct = pct  # keep raw value to check for 100% completion
                    
                    if not supports_progress2:
                        # Fallback: estimate overall progress using to-chk if available
                        to_chk_match = re.search(r'to-chk=(\d+)/(\d+)', line)
                        if to_chk_match:
                            remaining = int(to_chk_match.group(1))
                            total = int(to_chk_match.group(2))
                            if total > 0:
                                last_total = total
                                last_remaining = remaining
                                pct = int((total - remaining) / total * 100)
                        elif last_total > 0:
                            completed = last_total - last_remaining
                            pct = int((completed + (pct / 100.0)) / last_total * 100)
                        else:
                            # Before first file completes, estimate raw progress capped at 5% max
                            pct = int(pct * 0.05)
                    
                    if pct > 99:
                        pct = 99
                    if pct > current_progress:
                        current_progress = pct
                    current_speed = speed
                    current_eta = eta
                    update_status(current_progress, current_speed, current_eta, "running")
                    
                    # Filter out intermediate progress spam from writing to the log file
                    if "to-chk" in line or "xfr#" in line or raw_pct == 100:
                        log_out.write(line)
                        log_out.flush()
                else:
                    log_out.write(line)
                    log_out.flush()

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
