"""
MQTT Notifications Plugin for LEDMatrix

Display text or images from HomeAssistant via MQTT. Supports dynamic topic
configuration with wildcard support for flexible notification handling that
interrupts the normal display rotation.

API Version: 1.0.0
"""

import logging
import json
import time
import base64
import threading
import uuid
from typing import Dict, Any, Optional
from pathlib import Path
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import os

try:
    import paho.mqtt.client as mqtt
except ImportError:
    paho = None
    mqtt = None

from src.plugin_system.base_plugin import BasePlugin

logger = logging.getLogger(__name__)


class MQTTNotificationsPlugin(BasePlugin):
    """
    MQTT Notifications plugin for displaying messages from HomeAssistant.
    
    Supports:
    - Text messages (scrolling or static)
    - Image messages (base64 or file paths)
    - Dynamic topic configuration with MQTT wildcard support
    - Automatic display interruption via on-demand system
    """
    
    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the MQTT notifications plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        
        if mqtt is None:
            raise ImportError("paho-mqtt is required. Install with: pip install paho-mqtt")
        
        # MQTT configuration
        mqtt_config = config.get('mqtt', {})
        self.mqtt_host = mqtt_config.get('host', 'localhost')
        self.mqtt_port = mqtt_config.get('port', 1883)
        self.mqtt_username = mqtt_config.get('username', '')
        self.mqtt_password = mqtt_config.get('password', '')
        self.mqtt_client_id = mqtt_config.get('client_id', 'ledmatrix-mqtt-notifications')
        self.mqtt_keepalive = mqtt_config.get('keepalive', 60)
        
        topics_config = mqtt_config.get('topics', ['homeassistant/ledmatrix/+'])
        
        # Handle backward compatibility: convert dict to array
        if isinstance(topics_config, dict):
            self.topics = list(topics_config.values())
            self.logger.warning("Deprecated: 'topics' as object. Use array format instead. Example: [\"homeassistant/ledmatrix/+\"]")
        elif isinstance(topics_config, str):
            # Single string, convert to array
            self.topics = [topics_config]
        elif isinstance(topics_config, list):
            self.topics = topics_config
        else:
            # Fallback to default
            self.topics = ['homeassistant/ledmatrix/+']
            self.logger.warning("Invalid topics format, using default: ['homeassistant/ledmatrix/+']")
        
        # Display configuration
        display_config = config.get('display', {})
        self.default_duration = display_config.get('default_duration', 10.0)
        
        # Text configuration
        text_config = config.get('text', {})
        self.font_path = text_config.get('font_path', 'assets/fonts/PressStart2P-Regular.ttf')
        self.font_size = text_config.get('font_size', 8)
        self.text_color = tuple(int(c) for c in text_config.get('text_color', [255, 255, 255]))
        self.bg_color = tuple(int(c) for c in text_config.get('background_color', [0, 0, 0]))
        self.scroll_enabled = text_config.get('scroll', True)
        self.scroll_speed = text_config.get('scroll_speed', 30)
        self.scroll_gap_width = text_config.get('scroll_gap_width', 32)
        
        # State
        self.mqtt_client: Optional[mqtt.Client] = None
        self.mqtt_thread: Optional[threading.Thread] = None
        self.mqtt_connected = False
        self.mqtt_reconnect_delay = 1.0
        self.mqtt_max_reconnect_delay = 60.0
        self.mqtt_stop_event = threading.Event()
        
        # Current message state
        self.current_message: Optional[Dict[str, Any]] = None
        self.message_lock = threading.Lock()
        self.scroll_pos = 0.0
        self.last_update_time = time.time()
        self.text_image_cache: Optional[Image.Image] = None
        self.image_cache: Optional[Image.Image] = None
        
        # Load font
        self.font = self._load_font()
        
        self.logger.info("MQTT Notifications plugin initialized")
        self.logger.info("MQTT broker: %s:%s", self.mqtt_host, self.mqtt_port)
        self.logger.info("Topics: %s", self.topics)
    
    def _load_font(self):
        """Load the specified font file (TTF or BDF)."""
        font_path = self.font_path
        
        # Resolve relative paths
        if not os.path.isabs(font_path):
            # Try multiple resolution strategies
            resolved_path = None
            
            # Strategy 1: Try as-is
            if os.path.exists(font_path):
                resolved_path = font_path
            else:
                # Strategy 2: Try relative to current working directory
                cwd_path = os.path.join(os.getcwd(), font_path)
                if os.path.exists(cwd_path):
                    resolved_path = cwd_path
                else:
                    # Strategy 3: Try relative to project root
                    plugin_dir = Path(__file__).parent
                    project_root = plugin_dir.parent.parent
                    project_path = project_root / font_path
                    if project_path.exists():
                        resolved_path = str(project_path)
            
            if resolved_path:
                font_path = resolved_path
            else:
                self.logger.warning("Font file not found: %s, using default", self.font_path)
                return ImageFont.load_default()
        
        if not os.path.exists(font_path):
            self.logger.warning("Font file not found: %s, using default", font_path)
            return ImageFont.load_default()
        
        try:
            if font_path.lower().endswith('.ttf'):
                font = ImageFont.truetype(font_path, self.font_size)
                self.logger.info("Loaded TTF font: %s", font_path)
                return font
            elif font_path.lower().endswith('.bdf'):
                try:
                    import freetype
                    face = freetype.Face(font_path)
                    face.set_pixel_sizes(0, self.font_size)
                    self.logger.info("Loaded BDF font: %s", font_path)
                    return face
                except ImportError:
                    self.logger.warning("freetype not available for BDF font, using default")
                    return ImageFont.load_default()
            else:
                self.logger.warning("Unsupported font type: %s", font_path)
                return ImageFont.load_default()
        except Exception as e:
            self.logger.error("Failed to load font %s: %s", font_path, e)
            return ImageFont.load_default()
    
    def _on_mqtt_connect(self, client, userdata, flags, rc):  # pylint: disable=unused-argument
        """Callback for MQTT connection."""
        if rc == 0:
            self.mqtt_connected = True
            self.mqtt_reconnect_delay = 1.0
            self.logger.info("Connected to MQTT broker")
            
            # Subscribe to all topics (supports wildcards)
            for topic in self.topics:
                client.subscribe(topic, qos=1)
                self.logger.info("Subscribed to topic: %s", topic)
        else:
            self.mqtt_connected = False
            self.logger.error("Failed to connect to MQTT broker, return code: %s", rc)
    
    def _on_mqtt_disconnect(self, client, userdata, rc):  # pylint: disable=unused-argument
        """Callback for MQTT disconnection."""
        self.mqtt_connected = False
        if rc != 0:
            self.logger.warning("Unexpected MQTT disconnection, return code: %s", rc)
        else:
            self.logger.info("Disconnected from MQTT broker")
    
    def _on_mqtt_message(self, client, userdata, msg):  # pylint: disable=unused-argument
        """Callback for MQTT message received."""
        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8')
            
            self.logger.info(f"Received MQTT message on topic: {topic}")
            self.logger.debug(f"Message payload: {payload[:200]}...")
            
            # Parse JSON payload
            try:
                message_data = json.loads(payload)
            except json.JSONDecodeError as e:
                self.logger.error(f"Invalid JSON in MQTT message: {e}")
                return
            
            # Determine message type from message or derive from topic
            msg_type = message_data.get('type')
            if not msg_type:
                # Derive type from topic name (last segment after /)
                topic_parts = topic.split('/')
                msg_type = topic_parts[-1] if topic_parts else 'notification'
                self.logger.debug(f"No type in message, derived from topic: {msg_type}")
            
            # Validate message structure
            if 'content' not in message_data:
                self.logger.error("Message missing 'content' field")
                return
            
            content = message_data.get('content', {})
            if 'text' not in content and 'image' not in content:
                self.logger.error("Message content must have 'text' or 'image' field")
                return
            
            # Build message object
            message = {
                'type': message_data.get('type', msg_type),
                'content': content,
                'duration': message_data.get('duration'),
                'priority': message_data.get('priority', 'normal'),
                'timestamp': time.time(),
                'topic': topic
            }
            
            # Use default duration if not provided in message
            if message['duration'] is None:
                message['duration'] = self.default_duration
            
            # Store message
            with self.message_lock:
                self.current_message = message
                # Clear caches when new message arrives
                self.text_image_cache = None
                self.image_cache = None
                self.scroll_pos = 0.0
            
            # Trigger on-demand display
            self._trigger_on_demand_display(message)
            
        except Exception as e:
            self.logger.error(f"Error processing MQTT message: {e}", exc_info=True)
    
    def _trigger_on_demand_display(self, message: Dict[str, Any]):
        """Trigger on-demand display via cache manager."""
        try:
            request_id = str(uuid.uuid4())
            request_payload = {
                'request_id': request_id,
                'action': 'start',
                'plugin_id': self.plugin_id,
                'mode': 'mqtt_notification',
                'duration': message.get('duration', self.default_duration),
                'pinned': False,
                'timestamp': time.time()
            }
            
            # Store message in cache for display method
            self.cache_manager.set(f'{self.plugin_id}_current_message', message, max_age=3600)
            
            # Trigger on-demand display
            self.cache_manager.set('display_on_demand_request', request_payload)
            
            self.logger.info("Triggered on-demand display for %s notification", message['type'])
            
        except Exception as e:
            self.logger.error(f"Error triggering on-demand display: {e}", exc_info=True)
    
    def _connect_mqtt(self):
        """Connect to MQTT broker."""
        try:
            # Handle paho-mqtt v2.x and v1.x API differences
            try:
                # paho-mqtt 2.0+ requires CallbackAPIVersion
                self.mqtt_client = mqtt.Client(
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
                    client_id=self.mqtt_client_id,
                    clean_session=True
                )
            except (TypeError, AttributeError):
                # paho-mqtt 1.x
                self.mqtt_client = mqtt.Client(
                    client_id=self.mqtt_client_id,
                    clean_session=True
                )
            
            # Set callbacks
            self.mqtt_client.on_connect = self._on_mqtt_connect
            self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
            self.mqtt_client.on_message = self._on_mqtt_message
            
            # Set credentials if provided
            if self.mqtt_username:
                self.mqtt_client.username_pw_set(self.mqtt_username, self.mqtt_password)
            
            # Connect
            self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, self.mqtt_keepalive)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error connecting to MQTT broker: {e}")
            return False
    
    def _mqtt_loop(self):
        """MQTT client loop in background thread."""
        while not self.mqtt_stop_event.is_set():
            try:
                if not self.mqtt_connected:
                    # Try to connect
                    if self._connect_mqtt():
                        # Start loop
                        self.mqtt_client.loop_start()
                    else:
                        # Wait before retry with exponential backoff
                        wait_time = min(self.mqtt_reconnect_delay, self.mqtt_max_reconnect_delay)
                        self.logger.info("Retrying MQTT connection in %.1f seconds...", wait_time)
                        if self.mqtt_stop_event.wait(wait_time):
                            break
                        self.mqtt_reconnect_delay *= 2
                else:
                    # Connected, just wait
                    if self.mqtt_stop_event.wait(1.0):
                        break
                    # Reset reconnect delay on successful connection
                    self.mqtt_reconnect_delay = 1.0
                    
            except Exception as e:
                self.logger.error(f"Error in MQTT loop: {e}", exc_info=True)
                self.mqtt_connected = False
                if self.mqtt_client:
                    try:
                        self.mqtt_client.loop_stop()
                        self.mqtt_client.disconnect()
                    except Exception:
                        pass
                    self.mqtt_client = None
                
                # Wait before retry
                wait_time = min(self.mqtt_reconnect_delay, self.mqtt_max_reconnect_delay)
                if self.mqtt_stop_event.wait(wait_time):
                    break
                self.mqtt_reconnect_delay *= 2
        
        # Cleanup
        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception:
                pass
            self.mqtt_client = None
        
        self.logger.info("MQTT loop thread stopped")
    
    def _load_image(self, image_source: str) -> Optional[Image.Image]:
        """Load image from base64 data URI or file path."""
        try:
            # Check if it's a base64 data URI
            if image_source.startswith('data:image'):
                # Extract base64 data
                _, data = image_source.split(',', 1)
                image_data = base64.b64decode(data)
                img = Image.open(BytesIO(image_data))
                self.logger.info("Loaded image from base64 data")
                return img
            else:
                # Assume it's a file path
                image_path = image_source
                
                # Resolve relative paths
                if not os.path.isabs(image_path):
                    # Try multiple resolution strategies
                    resolved_path = None
                    
                    # Strategy 1: Try as-is
                    if os.path.exists(image_path):
                        resolved_path = image_path
                    else:
                        # Strategy 2: Try relative to current working directory
                        cwd_path = os.path.join(os.getcwd(), image_path)
                        if os.path.exists(cwd_path):
                            resolved_path = cwd_path
                        else:
                            # Strategy 3: Try relative to project root
                            plugin_dir = Path(__file__).parent
                            project_root = plugin_dir.parent.parent
                            project_path = project_root / image_path
                            if project_path.exists():
                                resolved_path = str(project_path)
                    
                    if resolved_path:
                        image_path = resolved_path
                    else:
                        self.logger.error("Image file not found: %s", image_source)
                        return None
                
                if not os.path.exists(image_path):
                    self.logger.error("Image file not found: %s", image_path)
                    return None
                
                img = Image.open(image_path)
                self.logger.info("Loaded image from file: %s", image_path)
                return img
                
        except Exception as e:
            self.logger.error("Error loading image: %s", e, exc_info=True)
            return None
    
    def _resize_image(self, img: Image.Image) -> Image.Image:
        """Resize image to fit matrix dimensions while maintaining aspect ratio."""
        matrix_width = self.display_manager.matrix.width if self.display_manager.matrix else 128
        matrix_height = self.display_manager.matrix.height if self.display_manager.matrix else 32
        
        # Calculate scaling to fit
        scale_w = matrix_width / img.width
        scale_h = matrix_height / img.height
        scale = min(scale_w, scale_h)
        
        new_width = int(img.width * scale)
        new_height = int(img.height * scale)
        
        # Resize with high-quality resampling
        resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Create new image with matrix dimensions and center the resized image
        if img.mode == 'RGBA':
            # Convert RGBA to RGB with black background
            background = Image.new('RGB', (matrix_width, matrix_height), self.bg_color)
            x_offset = (matrix_width - new_width) // 2
            y_offset = (matrix_height - new_height) // 2
            background.paste(resized, (x_offset, y_offset), resized if img.mode == 'RGBA' else None)
            return background
        else:
            # Convert to RGB if needed
            if resized.mode != 'RGB':
                resized = resized.convert('RGB')
            
            # Create centered image
            centered = Image.new('RGB', (matrix_width, matrix_height), self.bg_color)
            x_offset = (matrix_width - new_width) // 2
            y_offset = (matrix_height - new_height) // 2
            centered.paste(resized, (x_offset, y_offset))
            return centered
    
    def _create_text_cache(self, text: str) -> Optional[Image.Image]:
        """Pre-render text onto an image for smooth scrolling."""
        if not text:
            return None
        
        try:
            matrix_height = self.display_manager.matrix.height if self.display_manager.matrix else 32
            
            # Create temporary image to measure text
            temp_img = Image.new('RGB', (1, 1))
            temp_draw = ImageDraw.Draw(temp_img)
            
            if isinstance(self.font, ImageFont.FreeTypeFont) or isinstance(self.font, ImageFont.ImageFont):
                bbox = temp_draw.textbbox((0, 0), text, font=self.font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
            else:
                # Fallback
                text_width = len(text) * 8
                text_height = self.font_size
            
            # Total width is text width plus gap
            cache_width = text_width + self.scroll_gap_width
            cache_height = matrix_height
            
            # Create cache image
            cache_img = Image.new('RGB', (cache_width, cache_height), self.bg_color)
            draw = ImageDraw.Draw(cache_img)
            
            # Calculate vertical centering
            y_pos = (cache_height - text_height) // 2 - (bbox[1] if isinstance(self.font, ImageFont.FreeTypeFont) else 0)
            
            # Draw text
            draw.text((0, y_pos), text, font=self.font, fill=self.text_color)
            
            return cache_img
            
        except Exception as e:
            self.logger.error("Error creating text cache: %s", e, exc_info=True)
            return None
    
    def update(self) -> None:
        """Update plugin state - check MQTT connection health."""
        # Connection health is managed by background thread
        # This method is called periodically by the plugin system
    
    def display(self, force_clear: bool = False) -> bool:
        """
        Display the current MQTT message.
        
        Args:
            force_clear: If True, clear display before rendering
            
        Returns:
            True if content was displayed, False otherwise
        """
        # Get current message from cache
        try:
            message = self.cache_manager.get(f'{self.plugin_id}_current_message', max_age=3600)
            if not message:
                # Try to get from instance variable as fallback
                with self.message_lock:
                    message = self.current_message
        except Exception as e:
            self.logger.debug(f"Error getting message from cache: {e}")
            with self.message_lock:
                message = self.current_message
        
        if not message:
            return False
        
        try:
            matrix_width = self.display_manager.matrix.width if self.display_manager.matrix else 128
            matrix_height = self.display_manager.matrix.height if self.display_manager.matrix else 32

            content = message.get('content', {})
            
            # Check if message has image
            if 'image' in content and content['image']:
                # Display image
                if self.image_cache is None:
                    img = self._load_image(content['image'])
                    if img:
                        self.image_cache = self._resize_image(img)
                    else:
                        # Fallback to text if image loading fails
                        if 'text' in content and content['text']:
                            self.logger.warning("Image loading failed, falling back to text")
                            content = {'text': content['text']}
                        else:
                            return False
                
                if self.image_cache:
                    # Display cached image
                    self.display_manager.image = self.image_cache.copy()
                    self.display_manager.update_display()
                    return True
            
            # Display text
            if 'text' in content and content['text']:
                text = content['text']
                
                # Update scroll position if scrolling
                if self.scroll_enabled:
                    current_time = time.time()
                    delta_time = current_time - self.last_update_time
                    self.last_update_time = current_time
                    
                    # Create text cache if needed
                    if self.text_image_cache is None:
                        self.text_image_cache = self._create_text_cache(text)
                    
                    if self.text_image_cache:
                        # Calculate if text needs scrolling
                        text_width = self.text_image_cache.width - self.scroll_gap_width
                        if text_width > matrix_width:
                            # Scrolling text
                            scroll_delta = delta_time * self.scroll_speed
                            self.scroll_pos += scroll_delta
                            
                            # Reset when scrolled past end
                            total_width = self.text_image_cache.width
                            if self.scroll_pos >= total_width:
                                self.scroll_pos = self.scroll_pos % total_width
                            
                            # Create display image
                            img = Image.new('RGB', (matrix_width, matrix_height), self.bg_color)
                            
                            scroll_int = int(self.scroll_pos)
                            cache_width = self.text_image_cache.width
                            
                            if scroll_int + matrix_width <= cache_width:
                                # Simple crop
                                segment = self.text_image_cache.crop((scroll_int, 0, scroll_int + matrix_width, matrix_height))
                                img.paste(segment, (0, 0))
                            else:
                                # Wrap-around
                                width1 = cache_width - scroll_int
                                if width1 > 0:
                                    segment1 = self.text_image_cache.crop((scroll_int, 0, cache_width, matrix_height))
                                    img.paste(segment1, (0, 0))
                                
                                remaining = matrix_width - width1
                                if remaining > 0:
                                    segment2 = self.text_image_cache.crop((0, 0, remaining, matrix_height))
                                    img.paste(segment2, (width1, 0))
                            
                            self.display_manager.image = img
                        else:
                            # Fallback: static text
                            img = Image.new('RGB', (matrix_width, matrix_height), self.bg_color)
                            draw = ImageDraw.Draw(img)
                            bbox = draw.textbbox((0, 0), text, font=self.font)
                            text_width = bbox[2] - bbox[0]
                            text_height = bbox[3] - bbox[1]
                            x_pos = (matrix_width - text_width) // 2
                            y_pos = (matrix_height - text_height) // 2 - bbox[1]
                            draw.text((x_pos, y_pos), text, font=self.font, fill=self.text_color)
                            self.display_manager.image = img
                    else:
                        # Fallback: static text
                        img = Image.new('RGB', (matrix_width, matrix_height), self.bg_color)
                        draw = ImageDraw.Draw(img)
                        bbox = draw.textbbox((0, 0), text, font=self.font)
                        text_width = bbox[2] - bbox[0]
                        text_height = bbox[3] - bbox[1]
                        x_pos = (matrix_width - text_width) // 2
                        y_pos = (matrix_height - text_height) // 2 - bbox[1]
                        draw.text((x_pos, y_pos), text, font=self.font, fill=self.text_color)
                        self.display_manager.image = img
                else:
                    # Static text (centered)
                    img = Image.new('RGB', (matrix_width, matrix_height), self.bg_color)
                    draw = ImageDraw.Draw(img)
                    bbox = draw.textbbox((0, 0), text, font=self.font)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]
                    x_pos = (matrix_width - text_width) // 2
                    y_pos = (matrix_height - text_height) // 2 - bbox[1]
                    draw.text((x_pos, y_pos), text, font=self.font, fill=self.text_color)
                    self.display_manager.image = img
                
                self.display_manager.update_display()
                return True
            
            return False
            
        except Exception as e:
            self.logger.error("Error displaying MQTT message: %s", e, exc_info=True)
            return False
    
    def get_display_duration(self) -> float:
        """Get display duration from current message or config."""
        try:
            message = self.cache_manager.get(f'{self.plugin_id}_current_message', max_age=3600)
            if message and message.get('duration'):
                return float(message['duration'])
        except Exception:
            pass
        
        return self.default_duration
    
    def validate_config(self) -> bool:
        """Validate plugin configuration."""
        if not super().validate_config():
            return False
        
        # Validate MQTT config
        if 'mqtt' not in self.config:
            self.logger.error("Missing 'mqtt' configuration")
            return False
        
        mqtt_config = self.config['mqtt']
        if 'host' not in mqtt_config:
            self.logger.error("Missing 'mqtt.host' configuration")
            return False
        
        if 'port' not in mqtt_config:
            self.logger.error("Missing 'mqtt.port' configuration")
            return False

        # Validate colors
        for color_name, color_value in [("text_color", self.text_color), ("background_color", self.bg_color)]:
            if not isinstance(color_value, tuple) or len(color_value) != 3:
                self.logger.error("Invalid %s: must be RGB tuple", color_name)
                return False
            if not all(0 <= c <= 255 for c in color_value):
                self.logger.error("Invalid %s: values must be 0-255", color_name)
                return False
        
        return True
    
    def on_enable(self) -> None:
        """Start MQTT client when plugin is enabled."""
        super().on_enable()
        
        if mqtt is None:
            self.logger.error("paho-mqtt not available, cannot start MQTT client")
            return
        
        # Start MQTT thread
        if self.mqtt_thread is None or not self.mqtt_thread.is_alive():
            self.mqtt_stop_event.clear()
            self.mqtt_thread = threading.Thread(target=self._mqtt_loop, daemon=True)
            self.mqtt_thread.start()
            self.logger.info("MQTT client thread started")
    
    def on_disable(self) -> None:
        """Stop MQTT client when plugin is disabled."""
        super().on_disable()
        
        # Stop MQTT thread
        if self.mqtt_thread and self.mqtt_thread.is_alive():
            self.mqtt_stop_event.set()
            if self.mqtt_client:
                try:
                    self.mqtt_client.loop_stop()
                    self.mqtt_client.disconnect()
                except Exception:
                    pass
            self.mqtt_thread.join(timeout=5.0)
            self.logger.info("MQTT client thread stopped")
    
    def cleanup(self) -> None:
        """Cleanup resources."""
        # Stop MQTT client
        if self.mqtt_thread and self.mqtt_thread.is_alive():
            self.mqtt_stop_event.set()
            if self.mqtt_client:
                try:
                    self.mqtt_client.loop_stop()
                    self.mqtt_client.disconnect()
                except Exception:
                    pass
            self.mqtt_thread.join(timeout=5.0)
        
        # Clear caches
        self.text_image_cache = None
        self.image_cache = None
        
        self.logger.info("MQTT Notifications plugin cleaned up")
    
    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = super().get_info()
        info.update({
            'mqtt_connected': self.mqtt_connected,
            'mqtt_host': self.mqtt_host,
            'mqtt_port': self.mqtt_port,
            'topics': self.topics,
            'current_message_type': self.current_message.get('type') if self.current_message else None
        })
        return info
