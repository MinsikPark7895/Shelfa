import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import '../styles/ChatWidget.css'
import { apiFetch } from '../api'

interface ChatMessage {
  role: 'user' | 'bot'
  text: string
  recommendedBookId?: string | null
  recommendedBookTitle?: string | null
  quickReplies?: string[]
}

// TODO: 실제 도서 카테고리 데이터가 추가되면 교체
const BOOK_CATEGORIES = ['추리/스릴러', '에세이', '자기계발', '소설', '인문/역사']

function ChatWidget() {
  const navigate = useNavigate()
  const [isOpen, setIsOpen] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: 'bot',
      text: '안녕하세요! Shelfa 도서관 AI 사서입니다. 어떤 책을 찾으시나요?',
      quickReplies: ['📚 책 추천받기'],
    },
  ])
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)

  const hasToken = !!localStorage.getItem('access_token')

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight })
  }, [messages, isOpen])

  if (!hasToken) return null

  const handleQuickReply = (reply: string) => {
    if (reply === '📚 책 추천받기') {
      setMessages((prev) => [
        ...prev,
        { role: 'user', text: reply },
        { role: 'bot', text: '어떤 종류의 책을 추천받으시겠어요?', quickReplies: BOOK_CATEGORIES },
      ])
      return
    }
    sendMessage(`${reply} 추천해줘`)
  }

  const sendMessage = async (text?: string) => {
    const message = (text ?? input).trim()
    if (!message || isSending) return

    setMessages((prev) => [...prev, { role: 'user', text: message }])
    setInput('')
    setIsSending(true)

    try {
      const res = await apiFetch('/chat/', {
        method: 'POST',
        body: JSON.stringify({ message }),
      })

      if (res.status === 429) {
        setMessages((prev) => [...prev, { role: 'bot', text: '잠시 후 다시 시도해 주세요. (1분에 5회까지 가능해요)' }])
        return
      }
      if (!res.ok) {
        setMessages((prev) => [...prev, { role: 'bot', text: '죄송합니다. 답변을 가져오지 못했어요.' }])
        return
      }

      const data = await res.json()
      setMessages((prev) => [
        ...prev,
        {
          role: 'bot',
          text: data.reply,
          recommendedBookId: data.recommended_book_id,
          recommendedBookTitle: data.recommended_book_title,
        },
      ])
    } catch {
      setMessages((prev) => [...prev, { role: 'bot', text: '네트워크 오류가 발생했어요. 잠시 후 다시 시도해 주세요.' }])
    } finally {
      setIsSending(false)
    }
  }

  return (
    <div className="chat-widget">
      {isOpen && (
        <div className="chat-window">
          <div className="chat-header">
            <span>🤖 AI 사서</span>
            <button className="chat-close-btn" onClick={() => setIsOpen(false)}>✕</button>
          </div>

          <div className="chat-messages" ref={listRef}>
            {messages.map((msg, idx) => (
              <div key={idx} className={`chat-bubble-row ${msg.role}`}>
                <div className="chat-bubble">
                  {msg.text}
                  {msg.recommendedBookId && (
                    <button
                      className="chat-book-card"
                      onClick={() => navigate(`/book/${msg.recommendedBookId}`)}
                    >
                      📖 {msg.recommendedBookTitle}
                    </button>
                  )}
                  {msg.quickReplies && idx === messages.length - 1 && (
                    <div className="chat-quick-replies">
                      {msg.quickReplies.map((reply) => (
                        <button
                          key={reply}
                          className="chat-quick-reply-btn"
                          onClick={() => handleQuickReply(reply)}
                          disabled={isSending}
                        >
                          {reply}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {isSending && (
              <div className="chat-bubble-row bot">
                <div className="chat-bubble chat-typing">입력 중...</div>
              </div>
            )}
          </div>

          <div className="chat-input-row">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') sendMessage() }}
              placeholder="메시지를 입력하세요"
              disabled={isSending}
            />
            <button onClick={sendMessage} disabled={isSending || !input.trim()}>전송</button>
          </div>
        </div>
      )}

      <button className="chat-toggle-btn" onClick={() => setIsOpen((prev) => !prev)}>
        {isOpen ? '✕' : '💬'}
      </button>
    </div>
  )
}

export default ChatWidget
