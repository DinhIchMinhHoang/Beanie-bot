"""
Minecraft Server Management Feature Module for Beanie Bot
Handles Azure VM control, SSH commands, and Minecraft server management
"""

import asyncio
import logging
import time
import os
from discord.ext import commands, tasks
from discord import app_commands
import discord
import paramiko
from mcstatus import JavaServer
try:
    from mcrcon import MCRcon
    RCON_PKG_AVAILABLE = True
except Exception:
    RCON_PKG_AVAILABLE = False


class MinecraftFeature(commands.Cog):
    def __init__(self, bot, compute_client, config):
        self.bot = bot
        self.tree = bot.tree
        self.compute_client = compute_client
        self.config = config
        
        # Track auto-shutdown state
        self.empty_check_count = 0
        self.last_request_channel_id = None
        self.manual_grace_until = 0
        
        # Start background tasks
        if self.compute_client:
            self.auto_shutdown_check.start()
        
        # Load last request channel
        self._load_last_request_channel()
    
    def _load_last_request_channel(self):
        """Load last request channel from file."""
        try:
            if os.path.exists(self.config.LAST_REQUEST_CHANNEL_FILE):
                with open(self.config.LAST_REQUEST_CHANNEL_FILE, "r", encoding="utf-8") as f:
                    val = f.read().strip()
                    if val:
                        self.last_request_channel_id = int(val)
        except Exception as e:
            logging.warning(f"Could not load last request channel: {e}")
    
    def _save_last_request_channel(self, channel_id):
        """Save last request channel to file."""
        try:
            self.last_request_channel_id = channel_id
            with open(self.config.LAST_REQUEST_CHANNEL_FILE, "w", encoding="utf-8") as f:
                f.write(str(channel_id))
        except Exception as e:
            logging.warning(f"Could not persist last request channel: {e}")
    
    # --- Azure & SSH Helpers ---
    
    def azure_start_vm(self):
        """Start Azure VM."""
        if not self.compute_client:
            raise RuntimeError("Azure not configured")
        async_action = self.compute_client.virtual_machines.begin_start(
            self.config.AZURE_RESOURCE_GROUP, 
            self.config.AZURE_VM_NAME
        )
        async_action.wait()
    
    def azure_stop_vm(self):
        """Stop/deallocate Azure VM."""
        if not self.compute_client:
            raise RuntimeError("Azure not configured")
        async_action = self.compute_client.virtual_machines.begin_deallocate(
            self.config.AZURE_RESOURCE_GROUP, 
            self.config.AZURE_VM_NAME
        )
        async_action.wait()
    
    def vm_is_running(self):
        """Check if VM is running."""
        if not self.compute_client:
            return False
        try:
            vm = self.compute_client.virtual_machines.get(
                self.config.AZURE_RESOURCE_GROUP, 
                self.config.AZURE_VM_NAME, 
                expand='instanceView'
            )
            return "running" in vm.instance_view.statuses[1].display_status.lower()
        except Exception:
            return False
    
    def ssh_command(self, command, timeout=10):
        """Execute SSH command on remote server."""
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            if not self.config.SSH_PASSWORD:
                return "SSH disabled: no SSH_PASSWORD configured"
            c.connect(
                hostname=self.config.SSH_HOST, 
                username=self.config.SSH_USER, 
                password=self.config.SSH_PASSWORD, 
                timeout=timeout
            )
            stdin, stdout, stderr = c.exec_command(command)
            output = stdout.read().decode(errors='ignore')
            err = stderr.read().decode(errors='ignore')
            c.close()
            if err:
                return output + "\nERR:\n" + err
            return output
        except Exception as e:
            return str(e)
    
    def wait_for_mc_shutdown(self, max_wait=None, poll_interval=None):
        """Wait for Minecraft server to shut down (systemd)."""
        if max_wait is None:
            max_wait = self.config.SHUTDOWN_MAX_WAIT
        if poll_interval is None:
            poll_interval = self.config.SHUTDOWN_POLL_INTERVAL
        
        start = time.time()
        if self.config.SSH_PASSWORD and self.config.SSH_HOST and self.config.SSH_USER:
            while time.time() - start < max_wait:
                try:
                    out = self.ssh_command('sudo systemctl is-active minecraft.service', timeout=5)
                    if isinstance(out, str) and out.strip() != "active":
                        return True
                except Exception:
                    pass
                time.sleep(poll_interval)
            return False
        
        if self.config.MC_SERVER_IP:
            while time.time() - start < max_wait:
                try:
                    server = JavaServer.lookup(self.config.MC_SERVER_IP)
                    _ = server.status()
                except Exception:
                    return True
                time.sleep(poll_interval)
            return False
        
        return False
    
    def rcon_command(self, command, timeout=10):
        """Execute RCON command on Minecraft server."""
        if not RCON_PKG_AVAILABLE:
            raise RuntimeError("mcrcon package not installed")
        if not self.config.RCON_ENABLED:
            raise RuntimeError("RCON not enabled in env")
        if not self.config.RCON_PASSWORD:
            raise RuntimeError("RCON password not configured")
        host = self.config.RCON_HOST or self.config.MC_SERVER_IP
        try:
            with MCRcon(host, self.config.RCON_PASSWORD, port=self.config.RCON_PORT) as mcr:
                out = mcr.command(command)
                return out
        except Exception:
            raise
    
    def get_current_player_count(self):
        """Get current player count on Minecraft server."""
        try:
            if self.config.RCON_ENABLED and RCON_PKG_AVAILABLE and self.config.RCON_PASSWORD and self.vm_is_running():
                try:
                    out = self.rcon_command('list')
                    import re
                    m = re.search(r"There are (\d+) of a max", out)
                    if m:
                        return int(m.group(1))
                    return 0
                except Exception:
                    pass
            if self.config.MC_SERVER_IP:
                try:
                    server = JavaServer.lookup(self.config.MC_SERVER_IP)
                    status_mc = server.status()
                    return int(status_mc.players.online)
                except Exception:
                    pass
            if self.config.SSH_PASSWORD and self.config.SSH_HOST and self.config.SSH_USER:
                try:
                    out = self.ssh_command('sudo systemctl is-active minecraft.service', timeout=5)
                    if isinstance(out, str) and out.strip() == "active":
                        return 1
                    return 0
                except Exception:
                    pass
        except Exception:
            return None
        return None
    
    async def async_get_player_count(self, timeout=5):
        """Async version of get_current_player_count."""
        try:
            if self.config.RCON_ENABLED and RCON_PKG_AVAILABLE and self.config.RCON_PASSWORD and self.vm_is_running():
                try:
                    out = await asyncio.wait_for(asyncio.to_thread(self.rcon_command, 'list'), timeout=timeout)
                    import re
                    m = re.search(r"There are (\d+) of a max", out)
                    if m:
                        return int(m.group(1))
                    return 0
                except Exception:
                    pass
            if self.config.MC_SERVER_IP:
                try:
                    status_mc = await asyncio.wait_for(
                        asyncio.to_thread(lambda: JavaServer.lookup(self.config.MC_SERVER_IP).status()), 
                        timeout=timeout
                    )
                    return int(status_mc.players.online)
                except Exception:
                    pass
            if self.config.SSH_PASSWORD and self.config.SSH_HOST and self.config.SSH_USER:
                try:
                    out = await asyncio.wait_for(asyncio.to_thread(self.ssh_command, 'sudo systemctl is-active minecraft.service', 5), timeout=timeout)
                    if isinstance(out, str) and out.strip() == "active":
                        return 1
                    return 0
                except Exception:
                    pass
        except Exception:
            return None
        return None
    
    # --- Background Tasks ---
    
    @tasks.loop(minutes=5)
    async def auto_shutdown_check(self):
        """Check for empty server and auto-shutdown if needed."""
        try:
            if not self.compute_client:
                return
            vm = self.compute_client.virtual_machines.get(
                self.config.AZURE_RESOURCE_GROUP, 
                self.config.AZURE_VM_NAME, 
                expand='instanceView'
            )
            if "running" not in vm.instance_view.statuses[1].display_status.lower():
                self.empty_check_count = 0
                try:
                    self.auto_shutdown_check.stop()
                except Exception:
                    pass
                return
            
            try:
                if self.config.RCON_ENABLED and RCON_PKG_AVAILABLE and self.config.RCON_PASSWORD:
                    try:
                        out = await asyncio.wait_for(asyncio.to_thread(self.rcon_command, 'list'), timeout=5)
                        import re
                        m = re.search(r"There are (\d+) of a max", out)
                        if m:
                            players = int(m.group(1))
                        else:
                            players = 0
                    except Exception:
                        players = 0
                else:
                    server = JavaServer.lookup(self.config.MC_SERVER_IP)
                    status_mc = server.status()
                    players = status_mc.players.online
            except Exception:
                players = 0
            
            if players == 0:
                self.empty_check_count += 1
            else:
                self.empty_check_count = 0
            
            if self.empty_check_count >= self.config.MAX_EMPTY_CHECKS:
                channel = None
                try:
                    if self.last_request_channel_id:
                        channel = self.bot.get_channel(self.last_request_channel_id)
                except Exception:
                    channel = None
                if not channel and self.config.AUTO_SHUTDOWN_CHANNEL_ID:
                    channel = self.bot.get_channel(self.config.AUTO_SHUTDOWN_CHANNEL_ID)
                
                if self.manual_grace_until and time.time() < self.manual_grace_until:
                    self.empty_check_count = 0
                    return
                
                if self.config.MC_SERVER_IP:
                    try:
                        status_mc = await asyncio.wait_for(
                            asyncio.to_thread(lambda: JavaServer.lookup(self.config.MC_SERVER_IP).status()), 
                            timeout=5
                        )
                    except Exception:
                        if channel:
                            await channel.send("⚠️ Không thể track được mcstatus - hủy auto-shutdown.")
                        self.empty_check_count = 0
                        return
                    players_now = int(status_mc.players.online)
                    if players_now > 0:
                        self.empty_check_count = 0
                        return
                    if channel:
                        await channel.send("⚠️ Không có ai chơi trong thời gian dài, Bot sẽ tắt máy để tiết kiệm chi phí.")
                else:
                    self.empty_check_count = 0
                    return
                
                await asyncio.to_thread(self.ssh_command, 'sudo systemctl stop minecraft.service')
                try:
                    confirmed = await asyncio.to_thread(self.wait_for_mc_shutdown, 45, 5)
                except Exception:
                    confirmed = False
                
                if not confirmed:
                    if channel:
                        await channel.send("⚠️ Auto-Shutdown: Server bị treo (Freeze). Thực hiện Force Kill...")
                    await asyncio.to_thread(self.ssh_command, 'pkill -9 -f java')
                    await asyncio.sleep(5)
                    confirmed = await asyncio.to_thread(self.wait_for_mc_shutdown, 10, 2)
                
                if confirmed:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, self.azure_stop_vm)
                    if channel:
                        await channel.send("💤 Đã tự động tắt máy thành công!")
                else:
                    if channel:
                        await channel.send("⚠️ Bot không thể xác nhận Minecraft đã tắt (kể cả sau khi Force Kill); VM sẽ KHÔNG tắt. Vui lòng kiểm tra.")
                
                self.empty_check_count = 0
        
        except Exception as e:
            logging.warning(f"auto_shutdown_check error: {e}")
    
    # --- Slash Commands ---
    
    @app_commands.command(name="status", description="Check Azure VM and Minecraft server status")
    async def status_cmd(self, interaction: discord.Interaction):
        """Check server status."""
        await interaction.response.defer()
        msg = ""
        try:
            if self.compute_client:
                vm = self.compute_client.virtual_machines.get(
                    self.config.AZURE_RESOURCE_GROUP, 
                    self.config.AZURE_VM_NAME, 
                    expand='instanceView'
                )
                vm_status = vm.instance_view.statuses[1].display_status
                msg += f"🖥️ **Azure VM:** {vm_status}\n"
            else:
                msg += "🖥️ **Azure VM:** Not configured\n"
        except Exception as e:
            msg += f"🖥️ **Azure VM:** Error - {e}\n"
        try:
            players_cnt = None
            if self.vm_is_running() and self.config.RCON_ENABLED and RCON_PKG_AVAILABLE and self.config.RCON_PASSWORD:
                try:
                    out = await asyncio.wait_for(asyncio.to_thread(self.rcon_command, "list"), timeout=5)
                    import re
                    m = re.search(r"There are (\d+) of a max", out)
                    if m:
                        players_cnt = int(m.group(1))
                        msg += f"🟢 **Minecraft (RCON):** {players_cnt} players\n"
                    else:
                        msg += "🟡 **Minecraft (RCON):** Unable to parse player count\n"
                except Exception:
                    players_cnt = None
            if players_cnt is None:
                if self.config.MC_SERVER_IP:
                    server = JavaServer.lookup(self.config.MC_SERVER_IP)
                    status_mc = server.status()
                    msg += f"🟢 **Minecraft:** Online ({status_mc.players.online} players) — Ping {int(status_mc.latency)}ms"
                else:
                    msg += "⚫ **Minecraft:** IP not configured"
        except Exception:
            msg += "⚫ **Minecraft:** Offline or starting"
        try:
            if self.last_request_channel_id:
                msg += f"\n🔔 **Requested by channel:** <#{self.last_request_channel_id}>"
        except Exception:
            pass
        await interaction.followup.send(msg)
    
    @app_commands.command(name="start", description="Start Azure VM and Minecraft server")
    async def start_cmd(self, interaction: discord.Interaction):
        """Start Azure VM and Minecraft server."""
        await interaction.response.defer()
        self._save_last_request_channel(interaction.channel_id)
        
        if not self.compute_client:
            await interaction.followup.send("❌ Azure chưa được cấu hình. Kiểm tra biến môi trường.")
            return
        
        loop = asyncio.get_running_loop()
        await interaction.followup.send("1️⃣ Bật Azure VM...")
        try:
            await loop.run_in_executor(None, self.azure_start_vm)
        except Exception as e:
            await interaction.followup.send(f"Lỗi khi bật VM: {e}")
            return
        
        await interaction.followup.send("✅ VM đã bật. Đợi 30s cho OS khởi động...")
        await asyncio.sleep(30)
        
        try:
            if not self.auto_shutdown_check.is_running():
                self.auto_shutdown_check.start()
        except Exception:
            pass
        
        await interaction.followup.send("2️⃣ Bật Minecraft server...")
        cmd = 'sudo systemctl start minecraft.service'
        out = await asyncio.to_thread(self.ssh_command, cmd)
        await interaction.followup.send(f"✅ Lệnh khởi động đã gửi: {out[:1000]}")
        
        start_poll = time.time()
        server_online = False
        while time.time() - start_poll < self.config.SHUTDOWN_MAX_WAIT:
            try:
                if self.config.MC_SERVER_IP:
                    server = JavaServer.lookup(self.config.MC_SERVER_IP)
                    status_mc = server.status()
                    server_online = True
                    players_online = status_mc.players.online
                    latency = int(status_mc.latency)
                else:
                    server_online = False
            except Exception:
                server_online = False
            
            if server_online:
                msg = ""
                try:
                    if self.compute_client:
                        vm = self.compute_client.virtual_machines.get(
                            self.config.AZURE_RESOURCE_GROUP, 
                            self.config.AZURE_VM_NAME, 
                            expand='instanceView'
                        )
                        vm_status = vm.instance_view.statuses[1].display_status
                        msg += f"🖥️ **Azure VM:** {vm_status}\n"
                    else:
                        msg += "🖥️ **Azure VM:** Not configured\n"
                except Exception as e:
                    msg += f"🖥️ **Azure VM:** Error - {e}\n"
                
                players_cnt = None
                if self.config.RCON_ENABLED and RCON_PKG_AVAILABLE and self.config.RCON_PASSWORD and self.vm_is_running():
                    try:
                        out_r = await asyncio.wait_for(asyncio.to_thread(self.rcon_command, "list"), timeout=5)
                        import re
                        m = re.search(r"There are (\d+) of a max", out_r)
                        if m:
                            players_cnt = int(m.group(1))
                    except Exception:
                        players_cnt = None
                
                if players_cnt is None:
                    msg += f"🟢 **Minecraft:** Online ({players_online} players) — Ping {latency}ms"
                else:
                    msg += f"🟢 **Minecraft (RCON):** {players_cnt} players"
                
                await interaction.followup.send(msg)
                
                try:
                    self.manual_grace_until = time.time() + (self.config.MANUAL_GRACE_MINUTES * 60)
                except Exception:
                    pass
                break
            
            await asyncio.sleep(5)
        
        if not server_online:
            await interaction.followup.send("⚠️ Máy chủ vẫn chưa online sau thời gian chờ; có thể server vẫn đang khởi động. Vui lòng kiểm tra lại sau.")
    
    @app_commands.command(name="stop", description="Stop Minecraft server and deallocate VM (Smart Force)")
    async def stop_cmd(self, interaction: discord.Interaction):
        """Stop Minecraft server and deallocate VM."""
        await interaction.response.defer()
        
        if not self.vm_is_running():
            await interaction.followup.send("⚫ **Azure VM:** already deallocated/offline — nothing to stop.")
            return
        
        await interaction.followup.send("🛑 Đang gửi lệnh tắt server...")
        
        try:
            await asyncio.to_thread(self.rcon_command, 'stop')
        except:
            pass
        await asyncio.to_thread(self.ssh_command, 'sudo systemctl stop minecraft.service')
        
        await interaction.followup.send("⏳ Đang chờ server lưu dữ liệu và tắt (45s)...")
        
        confirmed = await asyncio.to_thread(self.wait_for_mc_shutdown, 45, 5)
        
        if not confirmed:
            await interaction.followup.send("⚠️ Server có vẻ bị treo (Freeze) sau 45s. Đang thực hiện Force Kill (pkill)...")
            await asyncio.to_thread(self.ssh_command, 'pkill -9 -f java')
            await asyncio.sleep(5)
            confirmed = await asyncio.to_thread(self.wait_for_mc_shutdown, 10, 2)
        
        if confirmed:
            if self.compute_client:
                loop = asyncio.get_running_loop()
                await interaction.followup.send("2️⃣ Minecraft đã tắt. Đang tắt Azure VM...")
                try:
                    await loop.run_in_executor(None, self.azure_stop_vm)
                    await interaction.followup.send("💤 Hệ thống đã tắt hoàn toàn.")
                except Exception as e:
                    await interaction.followup.send(f"Lỗi khi tắt VM: {e}")
            else:
                await interaction.followup.send("Azure không được cấu hình; chỉ gửi lệnh stop đến MC.")
        else:
            await interaction.followup.send("❌ CỰC KỲ NGUY HIỂM: Không thể tắt process Java dù đã Force Kill. VM sẽ GIỮ NGUYÊN để bạn kiểm tra.")
    
    @app_commands.command(name="restart_mc", description="Restart Minecraft server only")
    async def restart_mc_cmd(self, interaction: discord.Interaction):
        """Restart Minecraft server only."""
        await interaction.response.defer()
        if not self.vm_is_running():
            await interaction.followup.send("⚫ **Azure VM:** already deallocated/offline — nothing to restart.")
            return
        
        await interaction.followup.send("🔄 Restarting Minecraft server...")
        if self.config.SSH_PASSWORD and self.config.SSH_HOST and self.config.SSH_USER:
            cmd = 'sudo systemctl restart minecraft.service'
            out = await asyncio.to_thread(self.ssh_command, cmd)
            await interaction.followup.send(f"✅ Restart command executed: {str(out)[:1000]}")
            try:
                self.manual_grace_until = time.time() + (self.config.MANUAL_GRACE_MINUTES * 60)
            except Exception:
                pass
            return
        
        if self.config.RCON_ENABLED and RCON_PKG_AVAILABLE and self.config.RCON_PASSWORD:
            try:
                await asyncio.to_thread(self.rcon_command, 'stop')
                await asyncio.sleep(5)
                await interaction.followup.send("✅ Sent RCON stop (graceful). Note: server start requires SSH access to run the start script.")
                return
            except Exception as e:
                await interaction.followup.send(f"⚠️ RCON stop failed: {e} and SSH not configured — cannot force restart.")
                return
        
        await interaction.followup.send("⚠️ Không thể thực hiện restart: SSH và RCON đều không được cấu hình.")
    
    @app_commands.command(name="mc", description="Send a command to the Minecraft server via RCON")
    @app_commands.describe(command="Minecraft command to execute (e.g. 'list', 'op PlayerName', 'time set day')")
    async def mc_cmd(self, interaction: discord.Interaction, command: str):
        """Execute a Minecraft server command via RCON."""
        await interaction.response.defer()
        self._save_last_request_channel(interaction.channel_id)

        if not self.config.RCON_ENABLED or not RCON_PKG_AVAILABLE or not self.config.RCON_PASSWORD:
            await interaction.followup.send("❌ RCON chưa được cấu hình hoặc chưa cài đặt.")
            return

        if not self.vm_is_running():
            await interaction.followup.send("⚫ VM không chạy — không thể gửi lệnh.")
            return

        try:
            out = await asyncio.wait_for(asyncio.to_thread(self.rcon_command, command), timeout=10)
            msg = f"✅ **Lệnh:** `/{command}`\n```\n{out[:1900]}\n```"
            await interaction.followup.send(msg)
        except Exception as e:
            await interaction.followup.send(f"❌ Lỗi khi gửi lệnh: {str(e)[:500]}")

    def cog_unload(self):
        """Called when cog is unloaded."""
        if self.auto_shutdown_check.is_running():
            self.auto_shutdown_check.cancel()


async def setup(bot):
    """Setup function for the Minecraft feature."""
    # This will be called by bot.load_extension()
    # The main.py should pass required dependencies
    pass
