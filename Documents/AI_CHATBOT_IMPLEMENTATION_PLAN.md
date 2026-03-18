# AI Chatbot Implementation Plan

## Overview
Each lesson will have its own AI chatbot that learns from the lesson transcript. The workflow involves:
1. **Admin uploads/pastes transcript** → Sends to training webhook
2. **AI learns from transcript** → Stores chatbot webhook reference
3. **Students interact with chatbot** → Uses chatbot webhook for Q&A

## Architecture

### Webhooks
- **Transcript Training Webhook**: `https://katalyst-crm2.fly.dev/webhook/425e8e67-2aa6-4c50-b67f-0162e2496b51`
  - Purpose: Receives transcript and trains the AI for that specific lesson
  - Input: Transcript text + Lesson metadata
  
- **Chatbot Webhook**: `https://katalyst-crm2.fly.dev/webhook/swi-chatbot`
  - Purpose: Handles chat interactions with the trained AI
  - Input: User message + Lesson context
  - Output: AI response

## Implementation Steps

### Phase 1: Database Schema Updates

#### Add Fields to Lesson Model
```python
# In myApp/models.py - Lesson model

# AI Chatbot Integration Fields
ai_chatbot_enabled = models.BooleanField(default=False, help_text="Whether AI chatbot is enabled for this lesson")
ai_chatbot_webhook_id = models.CharField(max_length=200, blank=True, help_text="Chatbot webhook ID from training")
ai_chatbot_trained_at = models.DateTimeField(null=True, blank=True, help_text="When transcript was sent for training")
ai_chatbot_training_status = models.CharField(
    max_length=20, 
    default='pending', 
    choices=[
        ('pending', 'Pending'),
        ('training', 'Training'),
        ('trained', 'Trained'),
        ('failed', 'Failed'),
    ],
    help_text="Status of AI training"
)
ai_chatbot_training_error = models.TextField(blank=True, help_text="Error message if training fails")
```

**Migration Required**: Create migration file to add these fields

---

### Phase 2: Admin Interface - Transcript Management

#### Location: `myApp/templates/creator/generate_lesson_ai.html`

Add a new section after the video preview section:

```html
<!-- AI Chatbot Transcript Section -->
<div class="bg-[#0a0e27]/60 backdrop-blur-sm border border-cyan-electric/10 rounded-xl p-6 mb-6">
    <div class="flex items-center justify-between mb-4">
        <h3 class="text-lg font-bold">AI Chatbot Setup</h3>
        <span class="px-3 py-1 rounded-full text-xs font-semibold
            {% if lesson.ai_chatbot_training_status == 'trained' %}bg-green-500/20 text-green-400 border border-green-500/30
            {% elif lesson.ai_chatbot_training_status == 'training' %}bg-yellow-500/20 text-yellow-400 border border-yellow-500/30
            {% elif lesson.ai_chatbot_training_status == 'failed' %}bg-red-500/20 text-red-400 border border-red-500/30
            {% else %}bg-gray-500/20 text-gray-400 border border-gray-500/30{% endif %}">
            {{ lesson.get_ai_chatbot_training_status_display|default:"Not Trained" }}
        </span>
    </div>
    
    <div class="space-y-4">
        <!-- Transcript Input Options -->
        <div>
            <label class="block text-sm font-medium mb-2">Lesson Transcript</label>
            <div class="flex gap-2 mb-2">
                <button type="button" id="use-existing-transcript" class="px-4 py-2 bg-cyan-electric/10 border border-cyan-electric/30 rounded-lg text-sm hover:bg-cyan-electric/20">
                    Use Existing Transcription
                </button>
                <button type="button" id="upload-transcript" class="px-4 py-2 bg-cyan-electric/10 border border-cyan-electric/30 rounded-lg text-sm hover:bg-cyan-electric/20">
                    Upload File
                </button>
            </div>
            
            <!-- Textarea for pasting transcript -->
            <textarea 
                id="transcript-input"
                name="transcript"
                rows="10"
                placeholder="Paste transcript here or use existing transcription..."
                class="w-full bg-[#0a0e27]/40 border border-cyan-electric/20 rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-cyan-electric/50 resize-none"
            >{{ lesson.transcription }}</textarea>
            
            <!-- File upload input (hidden) -->
            <input type="file" id="transcript-file-input" accept=".txt,.md,.doc,.docx" class="hidden">
        </div>
        
        <!-- Training Status Display -->
        {% if lesson.ai_chatbot_training_status == 'trained' %}
        <div class="bg-green-500/10 border border-green-500/30 rounded-lg p-4">
            <div class="flex items-center gap-2 text-green-400">
                <i class="fas fa-check-circle"></i>
                <span>AI Chatbot trained successfully on {{ lesson.ai_chatbot_trained_at|date:"M d, Y H:i" }}</span>
            </div>
        </div>
        {% elif lesson.ai_chatbot_training_status == 'training' %}
        <div class="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-4">
            <div class="flex items-center gap-2 text-yellow-400">
                <i class="fas fa-spinner fa-spin"></i>
                <span>Training in progress...</span>
            </div>
        </div>
        {% elif lesson.ai_chatbot_training_status == 'failed' %}
        <div class="bg-red-500/10 border border-red-500/30 rounded-lg p-4">
            <div class="flex items-center gap-2 text-red-400">
                <i class="fas fa-exclamation-circle"></i>
                <span>Training failed: {{ lesson.ai_chatbot_training_error|truncatewords:20 }}</span>
            </div>
        </div>
        {% endif %}
        
        <!-- Train Button -->
        <button 
            type="button" 
            id="train-chatbot-btn"
            class="w-full px-6 py-3 bg-purple-accent text-white rounded-full font-bold hover:bg-purple-accent/90 transition-all"
            {% if not lesson.transcription and not lesson.ai_chatbot_training_status == 'trained' %}disabled{% endif %}
        >
            <i class="fas fa-robot mr-2"></i> Train AI Chatbot
        </button>
    </div>
</div>
```

#### JavaScript for Transcript Management
Add to the template's `extra_js` block:

```javascript
// Transcript management
document.getElementById('use-existing-transcript')?.addEventListener('click', function() {
    const transcriptInput = document.getElementById('transcript-input');
    transcriptInput.value = '{{ lesson.transcription|escapejs }}';
});

document.getElementById('upload-transcript')?.addEventListener('click', function() {
    document.getElementById('transcript-file-input').click();
});

document.getElementById('transcript-file-input')?.addEventListener('change', function(e) {
    const file = e.target.files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = function(event) {
            document.getElementById('transcript-input').value = event.target.result;
        };
        reader.readAsText(file);
    }
});

// Train chatbot button
document.getElementById('train-chatbot-btn')?.addEventListener('click', async function() {
    const transcript = document.getElementById('transcript-input').value.trim();
    const lessonId = {{ lesson.id }};
    
    if (!transcript) {
        alert('Please provide a transcript');
        return;
    }
    
    this.disabled = true;
    this.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i> Training...';
    
    try {
        const response = await fetch(`/api/lessons/${lessonId}/train-chatbot/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': '{{ csrf_token }}'
            },
            body: JSON.stringify({
                transcript: transcript
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Reload page to show updated status
            window.location.reload();
        } else {
            alert('Error: ' + (data.error || 'Failed to train chatbot'));
            this.disabled = false;
            this.innerHTML = '<i class="fas fa-robot mr-2"></i> Train AI Chatbot';
        }
    } catch (error) {
        alert('Error: ' + error.message);
        this.disabled = false;
        this.innerHTML = '<i class="fas fa-robot mr-2"></i> Train AI Chatbot';
    }
});
```

---

### Phase 3: Backend API - Training Endpoint

#### Add to `myApp/views.py`:

```python
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
import requests
import json

@staff_member_required
@require_http_methods(["POST"])
def train_lesson_chatbot(request, lesson_id):
    """Send transcript to training webhook and update lesson status"""
    lesson = get_object_or_404(Lesson, id=lesson_id)
    
    try:
        data = json.loads(request.body)
        transcript = data.get('transcript', '').strip()
        
        if not transcript:
            return JsonResponse({'success': False, 'error': 'Transcript is required'}, status=400)
        
        # Update lesson status
        lesson.transcription = transcript
        lesson.ai_chatbot_training_status = 'training'
        lesson.save()
        
        # Prepare payload for training webhook
        training_webhook_url = 'https://katalyst-crm2.fly.dev/webhook/425e8e67-2aa6-4c50-b67f-0162e2496b51'
        
        payload = {
            'transcript': transcript,
            'lesson_id': lesson.id,
            'lesson_title': lesson.title,
            'course_name': lesson.course.name,
            'lesson_slug': lesson.slug,
        }
        
        # Send to training webhook
        try:
            response = requests.post(
                training_webhook_url,
                json=payload,
                timeout=30,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 200:
                response_data = response.json()
                
                # Store chatbot webhook ID if returned
                chatbot_webhook_id = response_data.get('chatbot_webhook_id') or response_data.get('webhook_id')
                
                if chatbot_webhook_id:
                    lesson.ai_chatbot_webhook_id = chatbot_webhook_id
                
                lesson.ai_chatbot_training_status = 'trained'
                lesson.ai_chatbot_trained_at = timezone.now()
                lesson.ai_chatbot_enabled = True
                lesson.save()
                
                return JsonResponse({
                    'success': True,
                    'message': 'Chatbot trained successfully',
                    'chatbot_webhook_id': chatbot_webhook_id
                })
            else:
                lesson.ai_chatbot_training_status = 'failed'
                lesson.ai_chatbot_training_error = f"Webhook returned status {response.status_code}: {response.text[:500]}"
                lesson.save()
                
                return JsonResponse({
                    'success': False,
                    'error': f'Training webhook returned error: {response.status_code}'
                }, status=500)
                
        except requests.exceptions.RequestException as e:
            lesson.ai_chatbot_training_status = 'failed'
            lesson.ai_chatbot_training_error = str(e)
            lesson.save()
            
            return JsonResponse({
                'success': False,
                'error': f'Failed to connect to training webhook: {str(e)}'
            }, status=500)
            
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        lesson.ai_chatbot_training_status = 'failed'
        lesson.ai_chatbot_training_error = str(e)
        lesson.save()
        
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
```

#### Add URL route in `myProject/urls.py`:

```python
path('api/lessons/<int:lesson_id>/train-chatbot/', views.train_lesson_chatbot, name='train_lesson_chatbot'),
```

---

### Phase 4: Student-Facing Chatbot Interface

#### Location: `myApp/templates/lesson.html`

Add chatbot section to the lesson page (in the right sidebar or as a floating widget):

```html
<!-- AI Chatbot Widget -->
{% if lesson.ai_chatbot_enabled and lesson.ai_chatbot_training_status == 'trained' %}
<div class="bg-[#0a0e27]/60 backdrop-blur-sm border border-purple-accent/20 rounded-xl p-4 mb-6">
    <div class="flex items-center justify-between mb-3">
        <h4 class="font-bold text-sm flex items-center gap-2">
            <i class="fas fa-robot text-purple-accent"></i>
            Lesson AI Assistant
        </h4>
        <button id="toggle-chatbot" class="text-gray-400 hover:text-white">
            <i class="fas fa-chevron-down" id="chatbot-icon"></i>
        </button>
    </div>
    
    <div id="chatbot-container" class="hidden">
        <div id="chatbot-messages" class="space-y-3 mb-4 max-h-96 overflow-y-auto">
            <div class="bg-purple-accent/10 border border-purple-accent/20 rounded-lg p-3 text-sm">
                <div class="flex items-start gap-2">
                    <i class="fas fa-robot text-purple-accent mt-1"></i>
                    <div>
                        <p class="font-semibold mb-1">AI Assistant</p>
                        <p class="text-gray-300">Hi! I'm your AI assistant for this lesson. Ask me anything about the content!</p>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="flex gap-2">
            <input 
                type="text" 
                id="chatbot-input" 
                placeholder="Ask a question..."
                class="flex-1 bg-[#0a0e27]/40 border border-purple-accent/20 rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-purple-accent/50"
            >
            <button 
                id="chatbot-send-btn"
                class="px-4 py-2 bg-purple-accent text-white rounded-lg hover:bg-purple-accent/90 transition-all"
            >
                <i class="fas fa-paper-plane"></i>
            </button>
        </div>
    </div>
</div>
{% endif %}
```

#### JavaScript for Chatbot (add to lesson.html or separate JS file):

```javascript
// Chatbot functionality
const chatbotContainer = document.getElementById('chatbot-container');
const toggleChatbot = document.getElementById('toggle-chatbot');
const chatbotIcon = document.getElementById('chatbot-icon');
const chatbotMessages = document.getElementById('chatbot-messages');
const chatbotInput = document.getElementById('chatbot-input');
const chatbotSendBtn = document.getElementById('chatbot-send-btn');

let chatbotOpen = false;

toggleChatbot?.addEventListener('click', function() {
    chatbotOpen = !chatbotOpen;
    if (chatbotOpen) {
        chatbotContainer.classList.remove('hidden');
        chatbotIcon.classList.remove('fa-chevron-down');
        chatbotIcon.classList.add('fa-chevron-up');
    } else {
        chatbotContainer.classList.add('hidden');
        chatbotIcon.classList.remove('fa-chevron-up');
        chatbotIcon.classList.add('fa-chevron-down');
    }
});

function addMessage(content, isUser = false) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `bg-${isUser ? 'cyan-electric' : 'purple-accent'}/10 border border-${isUser ? 'cyan-electric' : 'purple-accent'}/20 rounded-lg p-3 text-sm`;
    
    const icon = isUser ? 'fa-user' : 'fa-robot';
    const color = isUser ? 'cyan-electric' : 'purple-accent';
    
    messageDiv.innerHTML = `
        <div class="flex items-start gap-2">
            <i class="fas ${icon} text-${color} mt-1"></i>
            <div class="flex-1">
                <p class="font-semibold mb-1">${isUser ? 'You' : 'AI Assistant'}</p>
                <p class="text-gray-300">${content}</p>
            </div>
        </div>
    `;
    
    chatbotMessages.appendChild(messageDiv);
    chatbotMessages.scrollTop = chatbotMessages.scrollHeight;
}

chatbotSendBtn?.addEventListener('click', sendMessage);
chatbotInput?.addEventListener('keypress', function(e) {
    if (e.key === 'Enter') {
        sendMessage();
    }
});

async function sendMessage() {
    const message = chatbotInput.value.trim();
    if (!message) return;
    
    // Add user message
    addMessage(message, true);
    chatbotInput.value = '';
    chatbotSendBtn.disabled = true;
    
    // Show loading
    const loadingDiv = document.createElement('div');
    loadingDiv.id = 'chatbot-loading';
    loadingDiv.className = 'bg-purple-accent/10 border border-purple-accent/20 rounded-lg p-3 text-sm';
    loadingDiv.innerHTML = `
        <div class="flex items-start gap-2">
            <i class="fas fa-robot text-purple-accent mt-1"></i>
            <div class="flex-1">
                <p class="font-semibold mb-1">AI Assistant</p>
                <p class="text-gray-300"><i class="fas fa-spinner fa-spin"></i> Thinking...</p>
            </div>
        </div>
    `;
    chatbotMessages.appendChild(loadingDiv);
    chatbotMessages.scrollTop = chatbotMessages.scrollHeight;
    
    try {
        const response = await fetch(`/api/lessons/{{ lesson.id }}/chatbot/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': '{{ csrf_token }}'
            },
            body: JSON.stringify({
                message: message
            })
        });
        
        const data = await response.json();
        
        // Remove loading
        loadingDiv.remove();
        
        if (data.success) {
            addMessage(data.response || 'I apologize, but I couldn\'t generate a response.');
        } else {
            addMessage('Sorry, I encountered an error. Please try again.');
        }
    } catch (error) {
        loadingDiv.remove();
        addMessage('Sorry, I encountered an error. Please try again.');
    } finally {
        chatbotSendBtn.disabled = false;
    }
}
```

---

### Phase 5: Backend API - Chatbot Interaction

#### Add to `myApp/views.py`:

```python
@login_required
@require_http_methods(["POST"])
def lesson_chatbot(request, lesson_id):
    """Handle chatbot interactions for a lesson"""
    lesson = get_object_or_404(Lesson, id=lesson_id)
    
    # Check if chatbot is enabled and trained
    if not lesson.ai_chatbot_enabled or lesson.ai_chatbot_training_status != 'trained':
        return JsonResponse({
            'success': False,
            'error': 'Chatbot is not available for this lesson'
        }, status=400)
    
    # Check if user has access to this lesson
    from .utils.access import has_course_access
    if not has_course_access(request.user, lesson.course):
        return JsonResponse({
            'success': False,
            'error': 'You do not have access to this lesson'
        }, status=403)
    
    try:
        data = json.loads(request.body)
        user_message = data.get('message', '').strip()
        
        if not user_message:
            return JsonResponse({'success': False, 'error': 'Message is required'}, status=400)
        
        # Use the chatbot webhook
        chatbot_webhook_url = 'https://katalyst-crm2.fly.dev/webhook/swi-chatbot'
        
        payload = {
            'message': user_message,
            'lesson_id': lesson.id,
            'lesson_title': lesson.title,
            'course_name': lesson.course.name,
            'user_id': request.user.id,
            'user_email': request.user.email,
            'chatbot_webhook_id': lesson.ai_chatbot_webhook_id,  # If webhook needs specific ID
        }
        
        # Send to chatbot webhook
        try:
            response = requests.post(
                chatbot_webhook_url,
                json=payload,
                timeout=30,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 200:
                response_data = response.json()
                
                # Extract AI response (adjust based on actual webhook response format)
                ai_response = response_data.get('response') or response_data.get('message') or response_data.get('text') or str(response_data)
                
                return JsonResponse({
                    'success': True,
                    'response': ai_response
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': f'Chatbot webhook returned error: {response.status_code}'
                }, status=500)
                
        except requests.exceptions.RequestException as e:
            return JsonResponse({
                'success': False,
                'error': f'Failed to connect to chatbot webhook: {str(e)}'
            }, status=500)
            
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
```

#### Add URL route in `myProject/urls.py`:

```python
path('api/lessons/<int:lesson_id>/chatbot/', views.lesson_chatbot, name='lesson_chatbot'),
```

---

## Database Migration

Create migration file:

```bash
python manage.py makemigrations myApp --name add_ai_chatbot_fields
python manage.py migrate
```

---

## Testing Checklist

- [ ] Admin can upload transcript file
- [ ] Admin can paste transcript text
- [ ] Admin can use existing transcription
- [ ] Training webhook receives transcript correctly
- [ ] Lesson status updates after training
- [ ] Chatbot webhook ID is stored
- [ ] Students can see chatbot on lesson page
- [ ] Students can send messages
- [ ] AI responses are displayed correctly
- [ ] Error handling works for failed training
- [ ] Error handling works for failed chat requests
- [ ] Access control prevents unauthorized users

---

## Future Enhancements

1. **Chat History**: Store chat conversations per user/lesson
2. **Analytics**: Track popular questions, response times
3. **Feedback System**: Allow users to rate responses
4. **Multi-language Support**: Support transcripts in different languages
5. **Batch Training**: Train multiple lessons at once
6. **Retraining**: Allow retraining with updated transcripts

---

## Notes

- The webhook URLs are hardcoded but could be moved to settings.py for easier configuration
- Consider adding rate limiting for chatbot requests
- May want to add caching for frequently asked questions
- Consider adding a "Clear Chat" button for users
- May want to add typing indicators for better UX


