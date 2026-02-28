// flutter_integration_example.dart
// 
// Paste this into your Flutter project.
// Shows how to call the AIRI Alex backend from Flutter.
//
// Dependencies needed in pubspec.yaml:
//   http: ^1.2.0
//   speech_to_text: ^6.6.2
//   url_launcher: ^6.3.0
//   uuid: ^4.4.2

import 'dart:convert';
import 'package:http/http.dart' as http;

// ─── Config ──────────────────────────────────────────────────────────────────

const String kBackendUrl = 'http://YOUR_SERVER_IP:8000'; // change this
const String kApiKey = '';       // set if REQUIRE_API_KEY=true
const String kSessionId = 'user_device_001'; // unique per user/device

// ─── Request Model ────────────────────────────────────────────────────────────

class AssistantRequest {
  final String text;
  final String sessionId;
  final bool partial;

  const AssistantRequest({
    required this.text,
    this.sessionId = kSessionId,
    this.partial = false,
  });

  Map<String, dynamic> toJson() => {
    'text': text,
    'session_id': sessionId,
    'partial': partial,
    'lang': 'en',
  };
}

// ─── Response Model ───────────────────────────────────────────────────────────

class AssistantResponse {
  final String intent;
  final double confidence;
  final String? appName;
  final String? appPackage;
  final String? contactName;
  final String? phoneNumber;
  final String? messageBody;
  final String? alarmTime;
  final int? timerSeconds;
  final String? reminderText;
  final String? reminderTime;
  final String? query;
  final String? location;
  final String? settingName;
  final bool? settingValue;
  final String? textResponse;
  final String routedBy;
  final int? latencyMs;

  const AssistantResponse({
    required this.intent,
    this.confidence = 1.0,
    this.appName,
    this.appPackage,
    this.contactName,
    this.phoneNumber,
    this.messageBody,
    this.alarmTime,
    this.timerSeconds,
    this.reminderText,
    this.reminderTime,
    this.query,
    this.location,
    this.settingName,
    this.settingValue,
    this.textResponse,
    this.routedBy = 'rule',
    this.latencyMs,
  });

  factory AssistantResponse.fromJson(Map<String, dynamic> j) => AssistantResponse(
    intent: j['intent'] ?? 'unknown',
    confidence: (j['confidence'] ?? 1.0).toDouble(),
    appName: j['app_name'],
    appPackage: j['app_package'],
    contactName: j['contact_name'],
    phoneNumber: j['phone_number'],
    messageBody: j['message_body'],
    alarmTime: j['alarm_time'],
    timerSeconds: j['timer_seconds'],
    reminderText: j['reminder_text'],
    reminderTime: j['reminder_time'],
    query: j['query'],
    location: j['location'],
    settingName: j['setting_name'],
    settingValue: j['setting_value'],
    textResponse: j['text_response'],
    routedBy: j['routed_by'] ?? 'rule',
    latencyMs: j['latency_ms'],
  );
}

// ─── API Service ──────────────────────────────────────────────────────────────

class AiriApiService {
  static final _client = http.Client();

  static Map<String, String> get _headers => {
    'Content-Type': 'application/json',
    if (kApiKey.isNotEmpty) 'X-API-Key': kApiKey,
  };

  /// Main: send transcribed text, get back action
  static Future<AssistantResponse?> process(String text, {bool partial = false}) async {
    try {
      final req = AssistantRequest(text: text, partial: partial);
      final res = await _client
          .post(
            Uri.parse('$kBackendUrl/api/v1/process'),
            headers: _headers,
            body: jsonEncode(req.toJson()),
          )
          .timeout(const Duration(seconds: 5));

      if (res.statusCode == 200) {
        return AssistantResponse.fromJson(jsonDecode(res.body));
      }
      print('Backend error: ${res.statusCode} ${res.body}');
    } catch (e) {
      print('API error: $e');
    }
    return null;
  }
}

// ─── Intent Executor ──────────────────────────────────────────────────────────

class IntentExecutor {
  /// Call this after receiving AssistantResponse from backend
  static Future<void> execute(AssistantResponse response) async {
    print('[AIRI] Intent: ${response.intent} | ${response.latencyMs}ms | ${response.routedBy}');

    switch (response.intent) {
      case 'open_app':
        await _openApp(response);
        break;
      case 'make_call':
        await _makeCall(response);
        break;
      case 'send_whatsapp':
        await _sendWhatsApp(response);
        break;
      case 'send_message':
        await _sendSms(response);
        break;
      case 'send_email':
        await _sendEmail(response);
        break;
      case 'web_search':
        await _webSearch(response);
        break;
      case 'navigate':
        await _navigate(response);
        break;
      case 'play_music':
        await _playMusic(response);
        break;
      case 'get_weather':
        // Handle in app UI
        break;
      case 'set_alarm':
      case 'set_timer':
      case 'set_reminder':
        // Use platform channels for native alarm/timer APIs
        await _setPlatformAlarm(response);
        break;
      case 'toggle_setting':
        await _toggleSetting(response);
        break;
      case 'take_photo':
        await _takePhoto();
        break;
      case 'llm_response':
        // Just speak text_response — no device action needed
        break;
      default:
        print('Unknown intent: ${response.intent}');
    }

    // Speak the response text
    if (response.textResponse != null) {
      await _speak(response.textResponse!);
    }
  }

  static Future<void> _openApp(AssistantResponse r) async {
    // Use url_launcher with android-app:// scheme
    // final url = 'android-app://${r.appPackage}';
    // await launchUrl(Uri.parse(url));
    print('Opening app: ${r.appName} (${r.appPackage})');
  }

  static Future<void> _makeCall(AssistantResponse r) async {
    // final url = 'tel:${r.phoneNumber ?? r.contactName}';
    // await launchUrl(Uri.parse(url));
    print('Calling: ${r.contactName}');
  }

  static Future<void> _sendWhatsApp(AssistantResponse r) async {
    // final url = 'whatsapp://send?phone=${r.phoneNumber}&text=${r.messageBody ?? ""}';
    // await launchUrl(Uri.parse(url));
    print('WhatsApp to: ${r.contactName}');
  }

  static Future<void> _sendSms(AssistantResponse r) async {
    // final url = 'sms:${r.phoneNumber}?body=${r.messageBody ?? ""}';
    // await launchUrl(Uri.parse(url));
    print('SMS to: ${r.contactName}');
  }

  static Future<void> _sendEmail(AssistantResponse r) async {
    // final url = 'mailto:${r.emailTo}?subject=${r.emailSubject}&body=${r.messageBody}';
    // await launchUrl(Uri.parse(url));
    print('Email to: ${r.contactName}');
  }

  static Future<void> _webSearch(AssistantResponse r) async {
    // final url = 'https://www.google.com/search?q=${Uri.encodeComponent(r.query ?? "")}';
    // await launchUrl(Uri.parse(url));
    print('Searching: ${r.query}');
  }

  static Future<void> _navigate(AssistantResponse r) async {
    // final url = 'https://www.google.com/maps/search/${Uri.encodeComponent(r.location ?? "")}';
    // await launchUrl(Uri.parse(url));
    print('Navigating to: ${r.location}');
  }

  static Future<void> _playMusic(AssistantResponse r) async {
    // Spotify: spotify://search/${r.query}
    // YouTube Music: youtubemusic://
    print('Playing: ${r.query}');
  }

  static Future<void> _setPlatformAlarm(AssistantResponse r) async {
    // Use MethodChannel to call native Android AlarmManager
    // const platform = MethodChannel('airi/alarm');
    // await platform.invokeMethod('setAlarm', {'time': r.alarmTime});
    print('Setting ${r.intent}: ${r.alarmTime ?? r.timerSeconds}');
  }

  static Future<void> _toggleSetting(AssistantResponse r) async {
    // Use MethodChannel for native settings toggle
    // const platform = MethodChannel('airi/settings');
    // await platform.invokeMethod('toggle', {'name': r.settingName, 'value': r.settingValue});
    print('Toggle ${r.settingName}: ${r.settingValue}');
  }

  static Future<void> _takePhoto() async {
    // Use image_picker package
    // final ImagePicker picker = ImagePicker();
    // await picker.pickImage(source: ImageSource.camera);
    print('Opening camera');
  }

  static Future<void> _speak(String text) async {
    // Use flutter_tts package
    // await flutterTts.speak(text);
    print('[TTS] $text');
  }
}

// ─── Usage Example ────────────────────────────────────────────────────────────
//
// In your speech_to_text onResult callback:
//
// void _onSpeechResult(SpeechRecognitionResult result) async {
//   if (result.finalResult) {
//     final response = await AiriApiService.process(result.recognizedWords);
//     if (response != null) {
//       await IntentExecutor.execute(response);
//     }
//   }
// }
