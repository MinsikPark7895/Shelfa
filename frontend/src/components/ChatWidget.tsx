import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import '../styles/ChatWidget.css'
import { apiFetch } from '../api'

interface SearchResult {
  id: string
  title: string
  author: string
  shelf_location: string
}

interface ChatMessage {
  role: 'user' | 'bot'
  text: string
  recommendedBookId?: string | null
  recommendedBookTitle?: string | null
  searchResults?: SearchResult[]
  quickReplies?: string[]
  isError?: boolean
  retryMessage?: string
}

type MenuLevel = 'initial' | 'search' | 'search-detail' | 'recommend'
type SearchMode = null | 'title' | 'category' | 'author' | 'recommend'

const INITIAL_MESSAGES: ChatMessage[] = [
  {
    role: 'bot',
    text: '안녕하세요! Shelfa 도서관 AI 사서입니다. 어떤 것이 필요하신가요?',
    quickReplies: ['📖 책 찾기', '🎯 추천받기'],
  },
]

const SEARCH_MENU_MESSAGES: ChatMessage[] = [
  ...INITIAL_MESSAGES,
  { role: 'user', text: '📖 책 찾기' },
  {
    role: 'bot',
    text: '어떤 방법으로 찾으시겠어요?',
    quickReplies: ['📝 제목으로 찾기', '🏷️ 카테고리로 찾기', '✍️ 작가로 찾기', '← 뒤로'],
  },
]

function ChatWidget() {
  const navigate = useNavigate()
  const [isOpen, setIsOpen] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>(INITIAL_MESSAGES)
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [menuLevel, setMenuLevel] = useState<MenuLevel>('initial')
  const [searchMode, setSearchMode] = useState<SearchMode>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const hasToken = !!localStorage.getItem('access_token')

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight })
  }, [messages, isOpen])

  if (!hasToken) return null

  const handleClose = () => {
    setIsOpen(false)
    setMessages(INITIAL_MESSAGES)
    setInput('')
    setMenuLevel('initial')
    setSearchMode(null)
  }

  const handleMinimize = () => {
    setIsOpen(false)
  }

  const handleBack = () => {
    setInput('')
    setSearchMode(null)
    if (menuLevel === 'search-detail') {
      setMenuLevel('search')
      setMessages(SEARCH_MENU_MESSAGES)
    } else {
      setMenuLevel('initial')
      setMessages(INITIAL_MESSAGES)
    }
  }

  const handleQuickReply = (reply: string) => {
    if (reply === '← 뒤로') { handleBack(); return }

    if (reply === '📖 책 찾기') {
      setMenuLevel('search')
      setMessages(SEARCH_MENU_MESSAGES)
      return
    }

    if (reply === '🎯 추천받기') {
      setMenuLevel('recommend')
      setSearchMode('recommend')
      setMessages((prev) => [
        ...prev,
        { role: 'user', text: reply },
        { role: 'bot', text: '어떤 책을 추천해드릴까요? 원하시는 분위기나 주제를 입력해주세요.', quickReplies: ['← 뒤로'] },
      ])
      return
    }

    if (reply === '📝 제목으로 찾기') {
      setMenuLevel('search-detail')
      setSearchMode('title')
      setMessages((prev) => [
        ...prev,
        { role: 'user', text: reply },
        { role: 'bot', text: '찾으시는 책의 제목을 입력해주세요.', quickReplies: ['← 뒤로'] },
      ])
      return
    }

    if (reply === '🏷️ 카테고리로 찾기') {
      setMenuLevel('search-detail')
      setSearchMode('category')
      setMessages((prev) => [
        ...prev,
        { role: 'user', text: reply },
        { role: 'bot', text: '어떤 카테고리의 책을 찾으시나요? 입력해주세요.', quickReplies: ['← 뒤로'] },
      ])
      return
    }

    if (reply === '✍️ 작가로 찾기') {
      setMenuLevel('search-detail')
      setSearchMode('author')
      setMessages((prev) => [
        ...prev,
        { role: 'user', text: reply },
        { role: 'bot', text: '찾으시는 작가명을 입력해주세요.', quickReplies: ['← 뒤로'] },
      ])
      return
    }
  }

  const buildMessage = (text: string): string => {
    if (searchMode === 'title') return `제목이 "${text}"인 책 찾아줘`
    if (searchMode === 'author') return `저자가 "${text}"인 책 찾아줘`
    if (searchMode === 'category') return `"${text}" 카테고리 책 추천해줘`
    return text
  }

  const handleOtherRecommend = () => {
    sendMessage('방금 추천해준 책 말고 다른 책 추천해줘')
  }

  const RESERVE_KEYWORDS = ['예약', '빌릴게', '빌려줘', '대출할게']

  const sendMessage = async (text?: string) => {
    const raw = (text ?? input).trim()
    if (!raw || isSending) return

    // 예약 키워드 감지 — 마지막 추천 도서 바로 예약
    const lastBotWithBook = [...messages].reverse().find(
      (m) => m.role === 'bot' && m.recommendedBookId
    )
    if (RESERVE_KEYWORDS.some((kw) => raw.includes(kw)) && lastBotWithBook?.recommendedBookId) {
      setMessages((prev) => [...prev, { role: 'user', text: raw }])
      setInput('')
      setIsSending(true)
      try {
        const res = await apiFetch(`/reservations/${lastBotWithBook.recommendedBookId}`, {
          method: 'POST',
        })
        if (res.ok) {
          setMessages((prev) => [
            ...prev,
            { role: 'bot', text: `"${lastBotWithBook.recommendedBookTitle}" 예약이 완료됐습니다! 로봇이 곧 책을 가져다 드릴게요. 🤖` },
          ])
        } else {
          const err = await res.json()
          setMessages((prev) => [
            ...prev,
            { role: 'bot', text: `예약에 실패했어요. ${err.detail || '다시 시도해주세요.'}` },
          ])
        }
      } catch {
        setMessages((prev) => [...prev, { role: 'bot', text: '서버 응답이 없어요.', isError: true, retryMessage: raw }])
      } finally {
        setIsSending(false)
      }
      return
    }

    // 제목/작가 검색은 AI 없이 검색 API 직접 호출
    if (searchMode === 'title' || searchMode === 'author') {
      setMessages((prev) => [...prev, { role: 'user', text: raw }])
      setInput('')
      setIsSending(true)
      try {
        const res = await apiFetch(`/books/search?query=${encodeURIComponent(raw)}&limit=50`)
        if (!res.ok) throw new Error()
        const data = await res.json()
        const books: SearchResult[] = data.items ?? data ?? []
        if (books.length === 0) {
          setMessages((prev) => [
            ...prev,
            { role: 'bot', text: `'${raw}'(으)로 검색한 결과가 없습니다.`, quickReplies: ['← 뒤로'] },
          ])
        } else {
          setMessages((prev) => [
            ...prev,
            {
              role: 'bot',
              text: `'${raw}'(으)로 검색한 결과 총 ${books.length}권이 있습니다.`,
              searchResults: books,
              quickReplies: ['← 뒤로'],
            },
          ])
        }
      } catch {
        setMessages((prev) => [...prev, { role: 'bot', text: '검색 중 오류가 발생했어요.', isError: true, retryMessage: raw }])
      } finally {
        setIsSending(false)
      }
      return
    }

    const message = buildMessage(raw)
    setMessages((prev) => [...prev, { role: 'user', text: raw }])
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
        setMessages((prev) => [...prev, { role: 'bot', text: '죄송합니다. 답변을 가져오지 못했어요.', isError: true, retryMessage: message }])
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
      setMessages((prev) => [...prev, { role: 'bot', text: '서버 응답이 없어요.', isError: true, retryMessage: message }])
    } finally {
      setIsSending(false)
    }
  }

  const retryMessage = async (message: string) => {
    setMessages((prev) => prev.filter((m) => !m.isError))
    setIsSending(true)
    try {
      const res = await apiFetch('/chat/', {
        method: 'POST',
        body: JSON.stringify({ message }),
      })
      if (!res.ok) {
        setMessages((prev) => [...prev, { role: 'bot', text: '서버 응답이 없어요.', isError: true, retryMessage: message }])
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
      setMessages((prev) => [...prev, { role: 'bot', text: '서버 응답이 없어요.', isError: true, retryMessage: message }])
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
            <div className="chat-header-btns">
              <button className="chat-minimize-btn" onClick={handleMinimize}>－</button>
              <button className="chat-close-btn" onClick={handleClose}>✕</button>
            </div>
          </div>

          <div className="chat-messages" ref={listRef}>
            {messages.map((msg, idx) => (
              <div key={idx} className={`chat-bubble-row ${msg.role}`}>
                <div className="chat-bubble">
                  {msg.text}
                  {msg.isError && msg.retryMessage && (
                    <button className="chat-retry-btn" onClick={() => retryMessage(msg.retryMessage!)} disabled={isSending}>
                      🔄 다시 시도
                    </button>
                  )}
                  {msg.searchResults && msg.searchResults.map((book) => (
                    <button
                      key={book.id}
                      className="chat-book-card"
                      onClick={() => navigate(`/book/${book.id}`)}
                    >
                      📖 {book.title}
                      <span className="chat-book-meta">{book.author} · {book.shelf_location}</span>
                    </button>
                  ))}
                  {msg.recommendedBookId && (
                    <>
                      <button className="chat-book-card" onClick={() => navigate(`/book/${msg.recommendedBookId}`)}>
                        📖 {msg.recommendedBookTitle}
                      </button>
                      {idx === messages.length - 1 && (
                        <button className="chat-other-recommend-btn" onClick={handleOtherRecommend} disabled={isSending}>
                          🔄 다른 책 추천받기
                        </button>
                      )}
                    </>
                  )}
                  {msg.quickReplies && idx === messages.length - 1 && (
                    <div className="chat-quick-replies">
                      {msg.quickReplies.map((reply) => (
                        <button
                          key={reply}
                          className={`chat-quick-reply-btn${reply === '← 뒤로' ? ' back' : ''}`}
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
              placeholder={
                searchMode === 'title' ? '제목을 입력하세요' :
                searchMode === 'category' ? '예: 로맨스, 판타지' :
                searchMode === 'author' ? '작가명을 입력하세요' :
                '메시지를 입력하세요'
              }
              disabled={isSending || !searchMode}
            />
            <button onClick={() => sendMessage()} disabled={isSending || !input.trim() || !searchMode}>전송</button>
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
