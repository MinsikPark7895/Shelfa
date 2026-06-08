import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import '../styles/Notifications.css'
import { apiFetch } from '../api'

interface Notification {
  id: string
  type: 'reserve' | 'return'
  message: string
  bookTitle: string
  bookMeta: string
  date: string
  bookId: string
}

const DISMISSED_KEY = 'dismissed_notifications'

function Notifications() {
  const navigate = useNavigate()
  const [notifications, setNotifications] = useState<Notification[]>([])

  useEffect(() => { fetchNotifications() }, [])

  const getDismissed = (): string[] => {
    try { return JSON.parse(localStorage.getItem(DISMISSED_KEY) || '[]') } catch { return [] }
  }

  const fetchNotifications = async () => {
    const notifs: Notification[] = []
    const dismissed = getDismissed()

    try {
      // 예약 중 도서 알림 (PENDING)
      const resRes = await apiFetch('/reservations/me?limit=50')
      if (resRes.ok) {
        const resData = await resRes.json()
        for (const r of (resData.items || []).filter((r: any) => r.status === 'PENDING')) {
          const id = `reserve-${r.id}`
          if (dismissed.includes(id)) continue
          notifs.push({
            id,
            type: 'reserve',
            message: '예약하신 도서가 준비되었습니다.',
            bookTitle: r.book.title,
            bookMeta: `${r.book.author || ''} / ${r.book.publisher || ''} / ${r.book.shelf_location || ''}`,
            date: r.reserved_at?.split('T')[0]?.replace(/-/g, '.') || '',
            bookId: r.book.id,
          })
        }
      }

      // 반납일 3일 이내 알림
      const loanRes = await apiFetch('/loans/me?limit=50')
      if (loanRes.ok) {
        const loanData = await loanRes.json()
        for (const l of (loanData.items || []).filter((l: any) => l.status === 'ACTIVE')) {
          const daysLeft = Math.ceil((new Date(l.due_date).getTime() - Date.now()) / (1000 * 60 * 60 * 24))
          if (daysLeft > 3) continue
          const id = `return-${l.id}`
          if (dismissed.includes(id)) continue
          notifs.push({
            id,
            type: 'return',
            message: `대출 도서의 반납일이 ${Math.max(0, daysLeft)}일 남았습니다.`,
            bookTitle: l.book.title,
            bookMeta: `${l.book.author || ''} / ${l.book.publisher || ''} / ${l.book.shelf_location || ''}`,
            date: l.due_date?.split('T')[0]?.replace(/-/g, '.') || '',
            bookId: l.book.id,
          })
        }
      }
    } catch { /* */ }
    setNotifications(notifs)
  }

  const handleDelete = (id: string) => {
    const dismissed = getDismissed()
    localStorage.setItem(DISMISSED_KEY, JSON.stringify([...dismissed, id]))
    setNotifications(prev => prev.filter(n => n.id !== id))
  }

  const handleClearAll = () => {
    const dismissed = getDismissed()
    const ids = notifications.map(n => n.id)
    localStorage.setItem(DISMISSED_KEY, JSON.stringify([...dismissed, ...ids]))
    setNotifications([])
  }

  return (
    <div className="page-container">
      <div className="top-nav">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
          <path d="M8 7h6" /><path d="M8 11h4" />
        </svg>
        <span className="logo-text">XYZ 도서관</span>
        {JSON.parse(localStorage.getItem('user') || '{}').role === 'admin' && (
          <button className="admin-nav-btn" onClick={() => navigate('/admin')}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
            </svg>
          </button>
        )}
      </div>

      <div className="noti-content">
        <div className="noti-header">
          <h1 className="noti-title">알림</h1>
          {notifications.length > 0 && (
            <button className="noti-clear-btn" onClick={handleClearAll}>전체 지우기</button>
          )}
        </div>

        {notifications.length === 0 ? (
          <div className="noti-empty">알림이 없습니다.</div>
        ) : (
          <div className="noti-list">
            {notifications.map(noti => (
              <div className="noti-item" key={noti.id}>
                <div className="noti-item-top">
                  <div className="noti-item-icon">
                    {noti.type === 'reserve' && (
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" /></svg>
                    )}
                    {noti.type === 'return' && (
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>
                    )}
                  </div>
                  <span className="noti-item-message">{noti.message}</span>
                  <button className="noti-item-delete" onClick={() => handleDelete(noti.id)}>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6" /><path d="M19 6l-1 14H6L5 6" /><path d="M10 11v6" /><path d="M14 11v6" /><path d="M9 6V4h6v2" /></svg>
                  </button>
                </div>
                <div className="noti-item-date">{noti.date}</div>
                <div className="noti-book-card" onClick={() => { handleDelete(noti.id); if (noti.type === 'reserve') { navigate('/my-library?tab=storage') } else { navigate(`/book/${noti.bookId}`) } }}>
                  <div className="noti-book-cover"></div>
                  <div className="noti-book-info">
                    <div className="noti-book-title">{noti.bookTitle}</div>
                    <div className="noti-book-meta">{noti.bookMeta}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="tab-bar">
        <a className="tab-item" onClick={() => navigate('/home')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" /></svg><span className="tab-label">홈</span></a>
        <a className="tab-item" onClick={() => navigate('/my-library')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /></svg><span className="tab-label">내 서재</span></a>
        <a className="tab-item" onClick={() => navigate('/mypage')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg><span className="tab-label">사용자</span></a>
        <a className="tab-item" onClick={() => navigate('/search')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg><span className="tab-label">검색</span></a>
        <a className="tab-item active" onClick={() => navigate('/notifications')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" /></svg><span className="tab-label">알림</span></a>
      </div>
    </div>
  )
}

export default Notifications
