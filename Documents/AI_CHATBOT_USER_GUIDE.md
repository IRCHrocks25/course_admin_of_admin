# AI Chatbot Feature - User Guide

## Overview
Each lesson can now have its own AI assistant that learns from the lesson transcript. This allows students to ask specific questions about the lesson content.

## For Administrators

### Setting Up AI Chatbot for a Lesson

1. **Navigate to Lesson Management**
   - Go to Dashboard → Lessons
   - Click "Edit" on the lesson you want to set up

2. **Add Transcript**
   You have three options:
   
   **Option A: Use Existing Transcription**
   - If the lesson already has a transcription from video processing, click "Use Existing Transcription"
   - The transcript will automatically populate the text area
   
   **Option B: Upload a File**
   - Click "Upload File"
   - Select a text file (.txt, .md) or Word document (.doc, .docx)
   - The content will be loaded into the text area
   
   **Option C: Paste Manually**
   - Simply paste the transcript text directly into the text area

3. **Train the AI**
   - Review the transcript in the text area
   - Click "Train AI Chatbot" button
   - Wait for the training to complete (usually takes a few moments)
   - You'll see a status indicator:
     - 🟡 **Training** - AI is learning from the transcript
     - 🟢 **Trained** - Ready for students to use
     - 🔴 **Failed** - Check the error message and try again

4. **Status Indicators**
   - **Not Trained** (Gray) - No chatbot available yet
   - **Training** (Yellow) - Training in progress
   - **Trained** (Green) - Chatbot is ready
   - **Failed** (Red) - Training failed, check error message

### Tips for Best Results
- Ensure the transcript is complete and accurate
- Include all important concepts and explanations
- The longer and more detailed the transcript, the better the AI responses
- You can retrain the chatbot anytime by updating the transcript and clicking "Retrain AI Chatbot"

## For Students

### Using the AI Assistant

1. **Access the Chatbot**
   - Navigate to any lesson that has an AI assistant enabled
   - Look for the "Lesson AI Assistant" in the right sidebar (desktop) or as a floating widget (mobile)
   - The header will show "Trained on this lesson" when available

2. **Ask Questions**
   - Type your question in the chat input at the bottom
   - Press Enter or click the send button
   - The AI will respond based on the lesson content

3. **Quick Actions**
   - Use the suggested quick actions for common requests:
     - 5-bullet summary
     - 3-step action plan
     - Delegation guide

4. **Features**
   - Clear chat history with the trash icon
   - Real-time responses
   - Context-aware answers based on the specific lesson

### Visual Indicators
- **Robot Icon** - Lesson-specific AI assistant (trained on this lesson)
- **Sparkles Icon** - General AI coach (not lesson-specific)
- **"Trained on this lesson"** badge - Confirms the AI knows this lesson's content

## Troubleshooting

### For Administrators

**Training Failed**
- Check that the transcript is not empty
- Verify your internet connection
- Check the error message for specific issues
- Try again with a fresh transcript

**Chatbot Not Appearing for Students**
- Ensure the training status is "Trained" (green)
- Check that `ai_chatbot_enabled` is set to `True`
- Verify the lesson is accessible to students

### For Students

**Chatbot Not Responding**
- Check your internet connection
- Ensure you have access to the lesson
- Try refreshing the page
- Contact support if the issue persists

**No Chatbot Available**
- Not all lessons have AI assistants enabled
- The lesson may not have been trained yet
- Check with your instructor

## Technical Details

### Webhooks Used
- **Training Webhook**: `https://katalyst-crm2.fly.dev/webhook/425e8e67-2aa6-4c50-b67f-0162e2496b51`
- **Chatbot Webhook**: `https://katalyst-crm2.fly.dev/webhook/swi-chatbot`

### Database Fields Added
- `ai_chatbot_enabled` - Boolean flag
- `ai_chatbot_webhook_id` - Stores webhook ID from training
- `ai_chatbot_trained_at` - Timestamp of training
- `ai_chatbot_training_status` - Status: pending, training, trained, failed
- `ai_chatbot_training_error` - Error message if training fails

## Migration

To apply the database changes, run:
```bash
python manage.py migrate
```

This will add the new fields to the Lesson model.


