// Chat functionality for Nautobot Chatbot plugin
(function() {
    const chatForm = document.getElementById('chatForm');
    const chatInput = document.getElementById('chatInput');
    const chatMessages = document.getElementById('chatMessages');
    const sendButton = document.getElementById('sendButton');
    const typingIndicator = document.getElementById('typingIndicator');
    const quickActions = document.querySelectorAll('.quick-action');

    // Generate session ID
    let sessionId = sessionStorage.getItem('chatSessionId');
    if (!sessionId) {
        sessionId = 'session_' + Date.now() + '_' + Math.random().toString(36).substring(7);
        sessionStorage.setItem('chatSessionId', sessionId);
    }

    // Add message to chat
    function addMessage(content, isUser = false) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `chat-message ${isUser ? 'user' : 'assistant'}`;

        const avatar = document.createElement('div');
        avatar.className = 'message-avatar';
        avatar.innerHTML = isUser ?
            '<i class="mdi mdi-account"></i>' :
            '<i class="mdi mdi-robot"></i>';

        const messageContent = document.createElement('div');
        messageContent.className = 'message-content';

        if (isUser) {
            const p = document.createElement('p');
            p.textContent = content;
            messageContent.appendChild(p);
        } else {
            // Format assistant messages (support for markdown-like formatting)
            messageContent.innerHTML = formatMessage(content);
        }

        messageDiv.appendChild(avatar);
        messageDiv.appendChild(messageContent);
        chatMessages.appendChild(messageDiv);

        // Scroll to bottom
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    // Format message content
    function formatMessage(content) {
        // Simple markdown-like formatting
        let formatted = content
            // Bold
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            // Italic
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            // Code blocks
            .replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
            // Inline code
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            // Line breaks
            .replace(/\n/g, '<br>');

        return `<div>${formatted}</div>`;
    }

    // Show typing indicator
    function showTyping() {
        typingIndicator.style.display = 'flex';
        sendButton.disabled = true;
        chatInput.disabled = true;
    }

    // Hide typing indicator
    function hideTyping() {
        typingIndicator.style.display = 'none';
        sendButton.disabled = false;
        chatInput.disabled = false;
    }

    // Send message to agent
    async function sendMessage(query) {
        if (!query.trim()) return;

        // Add user message
        addMessage(query, true);
        chatInput.value = '';

        // Show typing indicator
        showTyping();

        try {
            const response = await fetch('/plugins/chatbot/api/chat/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    query: query,
                    session_id: sessionId,
                }),
            });

            const data = await response.json();

            if (data.error) {
                addMessage(`Error: ${data.error}`, false);
            } else {
                addMessage(data.response, false);

                // Show tool calls if any
                if (data.tool_calls && data.tool_calls.length > 0) {
                    const toolsInfo = data.tool_calls.map(tc => tc.tool).join(', ');
                    console.log('Tools called:', toolsInfo);
                }
            }
        } catch (error) {
            console.error('Error:', error);
            addMessage('Sorry, I encountered an error. Please try again.', false);
        } finally {
            hideTyping();
            chatInput.focus();
        }
    }

    // Handle form submission
    chatForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const query = chatInput.value;
        sendMessage(query);
    });

    // Handle Enter key (Shift+Enter for new line)
    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            chatForm.dispatchEvent(new Event('submit'));
        }
    });

    // Handle quick actions
    quickActions.forEach(button => {
        button.addEventListener('click', () => {
            const query = button.getAttribute('data-query');
            chatInput.value = query;
            sendMessage(query);
        });
    });

    // Focus input on load
    chatInput.focus();
})();
