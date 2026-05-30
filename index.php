<?php
// aaPanel Linux Panel Plugin for PHP
// @author Ant Web Studio
// @homepage https://antwebstudio.com

// Ensure PLU_PATH is defined for local test environments (e.g. Laragon on Windows)
if (!defined('PLU_PATH')) {
    define('PLU_PATH', __DIR__);
}

class bt_main {
    
    // Internal helper to invoke the Python SSH script
    private function run_helper($action, $args = []) {
        $args['action'] = $action;
        $json_input = json_encode($args);
        
        $python_bin = "/www/server/panel/pyenv/bin/python";
        if (!file_exists($python_bin)) {
            $python_bin = "python"; // Fallback to system python
        }
        $script = PLU_PATH . "/ssh_helper.py";
        
        if (!file_exists($script)) {
            return [
                "status" => false,
                "message" => "SSH Helper script not found at " . $script,
                "msg" => "SSH Helper script not found at " . $script
            ];
        }
        
        $descriptors = [
            0 => ["pipe", "r"], // stdin
            1 => ["pipe", "w"], // stdout
            2 => ["pipe", "w"]  // stderr
        ];
        
        $process = proc_open("$python_bin " . escapeshellarg($script), $descriptors, $pipes);
        if (is_resource($process)) {
            fwrite($pipes[0], $json_input);
            fclose($pipes[0]);
            
            $stdout = stream_get_contents($pipes[1]);
            fclose($pipes[1]);
            
            $stderr = stream_get_contents($pipes[2]);
            fclose($pipes[2]);
            
            proc_close($process);
            
            $decoded = json_decode($stdout, true);
            if ($decoded === null) {
                $err_msg = "Failed to parse helper output: " . $stdout . ($stderr ? " Stderr: " . $stderr : "");
                return [
                    "status" => false,
                    "message" => $err_msg,
                    "msg" => $err_msg
                ];
            }
            return $decoded;
        }
        return [
            "status" => false,
            "message" => "Failed to execute helper process.",
            "msg" => "Failed to execute helper process."
        ];
    }

    // Retrieve saved SSH nodes from aaPanel databases (or mock nodes in dev environment)
    public function get_ssh_nodes() {
        return $this->run_helper("hosts");
    }

    // Retrieve saved Websites from aaPanel databases (or mock sites in dev environment)
    public function get_websites() {
        return $this->run_helper("sites");
    }

    // Test SSH connection (supports both saved Node IDs or custom detail parameters)
    public function test_connection() {
        $params = _post();
        if (!empty($params['_b64'])) {
            if (isset($params['password'])) $params['password'] = base64_decode($params['password']);
            if (isset($params['key'])) $params['key'] = base64_decode($params['key']);
        }
        return $this->run_helper("test", $params);
    }

    // List remote folders on the SSH target
    public function list_remote_dir() {
        $params = _post();
        if (empty($params['path'])) {
            $params['path'] = "/";
        }
        return $this->run_helper("list", $params);
    }

    // Launch background file transfer using rsync in python helper
    public function start_copy() {
        $params = _post();
        if (!empty($params['_b64'])) {
            if (isset($params['password'])) $params['password'] = base64_decode($params['password']);
            if (isset($params['key'])) $params['key'] = base64_decode($params['key']);
        }
        if (!empty($params['_db_b64'])) {
            if (isset($params['db_password'])) $params['db_password'] = base64_decode($params['db_password']);
        }
        
        // Basic validations
        $db_only = !empty($params['db_only']) ? true : false;
        if (!$db_only && (empty($params['remote_dir']) || empty($params['local_dir']))) {
            return [
                "status" => false,
                "message" => "Remote directory and local directory are both required.",
                "msg" => "Remote directory and local directory are both required."
            ];
        }

        if (empty($params['node_id']) && empty($params['host'])) {
            return [
                "status" => false,
                "message" => "You must select a saved node or enter custom server details.",
                "msg" => "You must select a saved node or enter custom server details."
            ];
        }

        $task_id = time() . "_" . rand(1000, 9999);
        $params['task_id'] = $task_id;
        $params['action'] = "copy";
        
        // Save copy arguments to a temporary config file (cross-platform temp folder)
        $config_dir = PLU_PATH;
        $config_file = $config_dir . DIRECTORY_SEPARATOR . "copy_config_" . $task_id . ".json";
        file_put_contents($config_file, json_encode($params));
        
        // Call helper in background
        $python_bin = "/www/server/panel/pyenv/bin/python";
        if (!file_exists($python_bin)) {
            $python_bin = "python";
        }
        $script = PLU_PATH . "/ssh_helper.py";
        
        // Windows/Linux cross-platform background execution
        if (strncasecmp(PHP_OS, 'WIN', 3) === 0) {
            // On Windows, run using start command (non-blocking)
            $cmd = 'start /B "" ' . escapeshellarg($python_bin) . ' ' . escapeshellarg($script) . ' < ' . escapeshellarg($config_file);
            pclose(popen($cmd, "r"));
            $pid = "1234"; // mock windows pid
        } else {
            // On Linux, run using nohup in the background
            $cmd = "nohup $python_bin " . escapeshellarg($script) . " < " . escapeshellarg($config_file) . " > /dev/null 2>&1 & echo \$!";
            $pid = trim(shell_exec($cmd));
        }
        
        // Log task in history database
        $history_file = PLU_PATH . DIRECTORY_SEPARATOR . "history.json";
        $history = [];
        if (file_exists($history_file)) {
            $history = json_decode(file_get_contents($history_file), true) ?: [];
        }
        
        $host_label = !empty($params['node_id']) ? "Saved Node #" . $params['node_id'] : $params['host'];
        
        $remote_path = !empty($params['remote_dir']) ? $params['remote_dir'] : "[DB: " . (!empty($params['db_name']) ? $params['db_name'] : 'Env parsed') . "]";
        $local_path = !empty($params['local_dir']) ? $params['local_dir'] : "[DB: " . (!empty($params['db_name']) ? $params['db_name'] : 'Env parsed') . "]";
        
        $history[] = [
            "task_id" => $task_id,
            "pid" => $pid,
            "host" => $host_label,
            "remote_dir" => $remote_path,
            "local_dir" => $local_path,
            "status" => "running",
            "started_at" => time(),
            "completed_at" => null,
            "error" => ""
        ];
        
        file_put_contents($history_file, json_encode($history));
        
        return [
            "status" => true,
            "message" => "Copy process initiated in the background.",
            "msg" => "Copy process initiated in the background.",
            "data" => [
                "task_id" => $task_id,
                "pid" => $pid
            ]
        ];
    }

    // Query active task copy progress & live terminal logs
    public function get_task_status() {
        $task_id = _post('task_id');
        if (!$task_id) {
            return [
                "status" => false,
                "message" => "Task ID is required.",
                "msg" => "Task ID is required."
            ];
        }
        
        $status_file = PLU_PATH . DIRECTORY_SEPARATOR . "copy_status_" . $task_id . ".json";
        $log_file = PLU_PATH . DIRECTORY_SEPARATOR . "copy_log_" . $task_id . ".log";
        
        $progress = 0;
        $speed = "";
        $eta = "";
        $task_status = "running";
        $error = "";
        
        if (file_exists($status_file)) {
            $data = json_decode(file_get_contents($status_file), true);
            if ($data) {
                $progress = isset($data['progress']) ? $data['progress'] : 0;
                $speed = isset($data['speed']) ? $data['speed'] : "";
                $eta = isset($data['eta']) ? $data['eta'] : "";
                $task_status = isset($data['status']) ? $data['status'] : "running";
                $error = isset($data['error']) ? $data['error'] : "";
            }
        }
        
        $logs = "";
        if (file_exists($log_file)) {
            $lines = array_slice(file($log_file), -2000); // fetch last 2000 lines
            $logs = implode("", $lines);
        }
        
        // Handle post-completion metadata updates in history
        if ($task_status === "success" || $task_status === "error") {
            $history_file = PLU_PATH . DIRECTORY_SEPARATOR . "history.json";
            if (file_exists($history_file)) {
                $history = json_decode(file_get_contents($history_file), true) ?: [];
                $updated = false;
                foreach ($history as &$item) {
                    if ($item['task_id'] === $task_id && $item['status'] === "running") {
                        $item['status'] = $task_status;
                        $item['completed_at'] = time();
                        $item['error'] = $error;
                        $updated = true;
                    }
                }
                if ($updated) {
                    file_put_contents($history_file, json_encode($history));
                }
            }
            
            // Clean up config file
            $config_file = PLU_PATH . DIRECTORY_SEPARATOR . "copy_config_" . $task_id . ".json";
            if (file_exists($config_file)) {
                unlink($config_file);
            }
        }
        
        return [
            "status" => true,
            "progress" => $progress,
            "speed" => $speed,
            "eta" => $eta,
            "task_status" => $task_status,
            "error" => $error,
            "logs" => $logs
        ];
    }

    // Cancel running copy background task
    public function cancel_task() {
        $task_id = _post('task_id');
        if (!$task_id) {
            return [
                "status" => false,
                "message" => "Task ID is required.",
                "msg" => "Task ID is required."
            ];
        }
        
        $history_file = PLU_PATH . DIRECTORY_SEPARATOR . "history.json";
        $pid = null;
        if (file_exists($history_file)) {
            $history = json_decode(file_get_contents($history_file), true) ?: [];
            foreach ($history as &$item) {
                if ($item['task_id'] === $task_id && $item['status'] === "running") {
                    $pid = $item['pid'];
                    $item['status'] = "cancelled";
                    $item['completed_at'] = time();
                }
            }
            file_put_contents($history_file, json_encode($history));
        }
        
        if ($pid && strncasecmp(PHP_OS, 'WIN', 3) !== 0) {
            shell_exec("kill -9 " . escapeshellarg($pid));
            shell_exec("pkill -P " . escapeshellarg($pid)); // terminate children
        }
        
        $status_file = PLU_PATH . DIRECTORY_SEPARATOR . "copy_status_" . $task_id . ".json";
        file_put_contents($status_file, json_encode([
            "progress" => 0,
            "speed" => "",
            "eta" => "",
            "status" => "error",
            "error" => "Copy cancelled by user.",
            "updated_at" => time()
        ]));
        
        return [
            "status" => true,
            "message" => "Background transfer process terminated.",
            "msg" => "Background transfer process terminated."
        ];
    }

    // Get historical records of folders transfer
    public function get_history() {
        $history_file = PLU_PATH . DIRECTORY_SEPARATOR . "history.json";
        if (file_exists($history_file)) {
            $history = json_decode(file_get_contents($history_file), true) ?: [];
            return array_reverse($history);
        }
        return [];
    }

    // Clear all transfer history
    public function clear_history() {
        $history_file = PLU_PATH . DIRECTORY_SEPARATOR . "history.json";
        if (file_exists($history_file)) {
            unlink($history_file);
        }
        return [
            "status" => true,
            "message" => "Transfer history database cleared.",
            "msg" => "Transfer history database cleared."
        ];
    }

    // Keeps default demo function for backwards compatibility checks
    public function phpinfo() {
        return phpinfo();
    }
}
?>