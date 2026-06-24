import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import '../styles/AdminPage.css'
import { apiFetch } from '../api'
import LiveMap from '../components/LiveMap'

interface UserItem {
  id: string
  name: string
  email: string
  role: string
  is_active: boolean
  created_at: string
  active_loans: number
  active_reservations: number
}

interface BookItem {
  id: string
  title: string
  author: string
  publisher: string
  shelf_location: string
  status: string
}

function AdminPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [activeTab, setActiveTab] = useState(searchParams.get('tab') || 'users')

  // 유저관리
  const [users, setUsers] = useState<UserItem[]>([])
  const [loading, setLoading] = useState(false)

  // 도서 목록
  const [bookList, setBookList] = useState<BookItem[] | null>(null)
  const [bookListLoading, setBookListLoading] = useState(false)
  const [bookListQuery, setBookListQuery] = useState(searchParams.get('q') || '')

  // 도서 등록
  const [bookLoading, setBookLoading] = useState(false)
  const [bookStep, setBookStep] = useState<'idle' | 'type' | 'count' | 'input'>('idle')
  const [isbnType, setIsbnType] = useState<10 | 13>(13)
  const [bookCount, setBookCount] = useState('')
  const [isbnList, setIsbnList] = useState<string[]>([])

  // 줄거리 동기화
  const [syncLoading, setSyncLoading] = useState(false)

  // 도서 삭제 안내 모달
  const [showDeleteNotice, setShowDeleteNotice] = useState(false)
  const [gearOpenId, setGearOpenId] = useState<string | null>(null)

  const fetchUsers = async () => {
    setLoading(true)
    try {
      const res = await apiFetch('/admin/users')
      if (res.ok) {
        const data = await res.json()
        setUsers(data.items || data || [])
      }
    } catch { /* */ } finally { setLoading(false) }
  }

  const fetchBookList = async (query: string) => {
    if (!query.trim()) return
    setBookListLoading(true)
    try {
      const res = await apiFetch(`/books/search?query=${encodeURIComponent(query)}&limit=100`)
      if (res.ok) {
        const data = await res.json()
        const sorted = (data.items || []).slice().sort((a: BookItem, b: BookItem) =>
          a.title.localeCompare(b.title, 'ko')
        )
        setBookList(sorted)
      }
    } catch { alert('도서 검색 중 오류가 발생했습니다.') } finally { setBookListLoading(false) }
  }

  useEffect(() => {
    const user = (() => { try { return JSON.parse(localStorage.getItem('user') || '{}') } catch { return {} } })()
    if (user.role !== 'admin') { navigate('/home'); return }
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (activeTab === 'users') fetchUsers()
    if (activeTab === 'books') {
      const q = searchParams.get('q') || ''
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (q) fetchBookList(q)
    }
  }, [activeTab])

  const handleSelectType = (type: 10 | 13) => {
    setIsbnType(type)
    setBookCount('')
    setIsbnList([])
    setBookStep('count')
  }

  const handleCountConfirm = () => {
    const n = parseInt(bookCount)
    if (!n || n < 1 || n > 50) { alert('1~50 사이로 입력해주세요.'); return }
    setIsbnList(Array(n).fill(''))
    setBookStep('input')
  }

  const handleIsbnChange = (idx: number, val: string) => {
    const digits = val.replace(/\D/g, '').slice(0, isbnType)
    setIsbnList(prev => prev.map((v, i) => i === idx ? digits : v))
  }

  const allFilled = isbnList.length > 0 && isbnList.every(v => v.length === isbnType)

  const handleBulkRegister = async () => {
    if (!allFilled) return
    setBookLoading(true)
    try {
      const res = await apiFetch('/books/bulk_register', {
        method: 'POST',
        body: JSON.stringify({ isbns: isbnList }),
      })
      if (res.ok) {
        const data = await res.json()
        const success = data.success_count ?? 0
        const failed: string[] = data.failed_isbns ?? []
        if (success === 0 && failed.length > 0) {
          alert(`등록 실패\n총 ${failed.length}권을 알라딘에서 찾지 못했습니다.\n실패 ISBN: ${failed.join(', ')}`)
        } else if (failed.length > 0) {
          alert(`${success}권 등록 완료\n${failed.length}권 실패: ${failed.join(', ')}`)
          setBookStep('idle')
          setIsbnList([])
          setBookCount('')
        } else {
          alert(`${success}권 등록 완료`)
          setBookStep('idle')
          setIsbnList([])
          setBookCount('')
        }
      } else {
        const err = await res.json().catch(() => ({}))
        alert(err?.detail || '등록에 실패했습니다.')
      }
    } catch { alert('서버 연결에 실패했습니다.') } finally { setBookLoading(false) }
  }

  const handleSyncDescriptions = async () => {
    if (!confirm('줄거리가 없는 도서를 일괄 업데이트합니다. 계속할까요?')) return
    setSyncLoading(true)
    try {
      const res = await apiFetch('/books/sync-descriptions', { method: 'POST' })
      if (res.ok) {
        alert('줄거리 동기화가 완료되었습니다.')
      } else {
        alert('동기화에 실패했습니다.')
      }
    } catch { alert('서버 연결에 실패했습니다.') } finally { setSyncLoading(false) }
  }

  const formatDate = (d: string) => {
    const dt = new Date(d)
    return `${dt.getFullYear()}.${String(dt.getMonth() + 1).padStart(2, '0')}.${String(dt.getDate()).padStart(2, '0')}`
  }

  return (
    <div className="page-container">
      <div className="top-nav">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
          <path d="M8 7h6" /><path d="M8 11h4" />
        </svg>
        <span className="logo-text">XYZ 도서관</span>
        <button className="admin-nav-btn" onClick={() => { if (activeTab === 'users') fetchUsers(); else if (activeTab === 'books') { setBookListQuery(''); setBookList(null) } }}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
          </svg>
        </button>
      </div>

      <div className="admin-content">
        <h1 className="admin-title">관리</h1>

        <div className="tab-group">
          <button className={`tab-btn ${activeTab === 'users' ? 'active' : ''}`} onClick={() => { setActiveTab('users'); setSearchParams({ tab: 'users' }); setBookStep('idle'); setIsbnList([]); setBookCount('') }}>유저관리</button>
          <button className={`tab-btn ${activeTab === 'books' ? 'active' : ''}`} onClick={() => { setActiveTab('books'); setSearchParams({ tab: 'books' }); setBookStep('idle'); setIsbnList([]); setBookCount('') }}>도서관리</button>
          <button className={`tab-btn ${activeTab === 'robot' ? 'active' : ''}`} onClick={() => { setActiveTab('robot'); setSearchParams({ tab: 'robot' }); setBookStep('idle'); setIsbnList([]); setBookCount('') }}>로봇관리</button>
        </div>

        {activeTab === 'users' && (
          <div className="admin-tab-content">
            {loading ? (
              <div className="admin-loading">불러오는 중...</div>
            ) : users.length === 0 ? (
              <div className="admin-empty">API 및 DB 연동 내용</div>
            ) : (
              <div className="admin-user-list">
                {users.map(user => (
                  <div className="admin-user-card" key={user.id}>
                    <div className="admin-user-row1">
                      <span className="admin-user-name">{user.name}</span>
                      <span className="admin-user-email">{user.email}</span>
                      <span className="admin-user-date">{formatDate(user.created_at)}</span>
                    </div>
                    <div className="admin-user-row2">
                      <div className="admin-user-badge-wrap">
                        <span className={`admin-role-badge ${user.role === 'admin' ? 'admin' : 'user'}`}>{user.role === 'admin' ? '관리자' : '사용자'}</span>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="admin-dropdown-icon"><polyline points="6 9 12 15 18 9" /></svg>
                      </div>
                      <div className="admin-user-badge-wrap">
                        <span className={`admin-active-badge ${user.is_active ? 'active' : 'inactive'}`}>{user.is_active ? '활성화' : '비활성화'}</span>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="admin-dropdown-icon"><polyline points="6 9 12 15 18 9" /></svg>
                      </div>
                      <span className="admin-user-stat">대출 {user.active_loans ?? '-'}권</span>
                      <span className="admin-user-stat">예약 {user.active_reservations ?? '-'}건</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'books' && (
          <div className="admin-tab-content">

            {/* 도서 목록 조회 */}
            <div className="admin-section">
              <h3 className="admin-section-title">도서 목록</h3>
              <div className="admin-book-search-row">
                <div className="admin-book-search-wrap">
                  <input
                    className="admin-book-search-input"
                    type="text"
                    placeholder="제목 검색"
                    value={bookListQuery}
                    onChange={(e) => setBookListQuery(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') { fetchBookList(bookListQuery); setSearchParams({ tab: 'books', q: bookListQuery }) } }}
                  />
                  {bookListQuery && (
                    <button className="admin-search-clear-btn" onClick={() => { setBookListQuery(''); setBookList(null) }}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                      </svg>
                    </button>
                  )}
                </div>
                <button className="admin-action-btn" onClick={() => { fetchBookList(bookListQuery); setSearchParams({ tab: 'books', q: bookListQuery }) }}>검색</button>
              </div>
              <div className="admin-book-result-area">
                {bookListLoading ? (
                  <div className="admin-loading">불러오는 중...</div>
                ) : bookList === null ? (
                  <div className="admin-book-empty">제목을 입력하여 검색하세요.</div>
                ) : bookList.length === 0 ? (
                  <div className="admin-book-empty">검색 결과가 없습니다.</div>
                ) : (
                  <div className="admin-book-list">
                    {bookList.map(book => (
                      <div className="admin-book-card" key={book.id} onClick={() => setGearOpenId(null)}>
                        <div className="admin-book-info">
                          <span className="admin-book-title">{book.title}</span>
                          <span className="admin-book-author">{book.author}</span>
                          <span className="admin-book-location">{book.shelf_location}</span>
                        </div>
                        <div className="admin-book-right">
                          <span className={`admin-book-status ${book.status === 'AVAILABLE' ? 'available' : 'unavailable'}`}>
                            {book.status === 'AVAILABLE' ? '대출가능' : '대출중'}
                          </span>
                          <div className="admin-gear-wrap">
                            <button className="admin-gear-btn" onClick={(e) => { e.stopPropagation(); setGearOpenId(gearOpenId === book.id ? null : book.id) }}>
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <circle cx="12" cy="12" r="3" />
                                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
                              </svg>
                            </button>
                            {gearOpenId === book.id && (
                              <div className="admin-gear-dropdown" onClick={(e) => e.stopPropagation()}>
                                <button className="admin-gear-item" onClick={() => { setGearOpenId(null); navigate(`/book/${book.id}`) }}>상세페이지 이동</button>
                                <button className="admin-gear-item" onClick={() => { setGearOpenId(null); setShowDeleteNotice(true) }}>도서 정보 수정</button>
                                <button className="admin-gear-item admin-gear-item--danger" onClick={() => { setGearOpenId(null); setShowDeleteNotice(true) }}>도서 삭제</button>
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* 도서 등록 */}
            <div className="admin-section">
              <h3 className="admin-section-title">도서 등록</h3>
              <p className="admin-section-desc">ISBN 바코드로 도서를 등록합니다. 2007년 이후 출판 도서는 ISBN-13을 사용하세요.</p>

              <div className="admin-step-box">
                {bookStep === 'idle' && (
                  <button className="admin-action-btn" onClick={() => setBookStep('type')}>도서 등록</button>
                )}

                {bookStep === 'type' && (
                  <>
                    <div className="admin-isbn-type-row">
                      <button className="admin-isbn-type-btn" onClick={() => handleSelectType(10)}>
                        <span className="admin-isbn-type-label">ISBN-10</span>
                        <span className="admin-isbn-type-sub">2007년 이전 도서</span>
                      </button>
                      <button className="admin-isbn-type-btn" onClick={() => handleSelectType(13)}>
                        <span className="admin-isbn-type-label">ISBN-13</span>
                        <span className="admin-isbn-type-sub">2007년 이후 도서</span>
                      </button>
                    </div>
                    <button className="admin-back-btn" onClick={() => { setBookStep('idle'); setIsbnList([]); setBookCount('') }}>이전으로</button>
                  </>
                )}

                {bookStep === 'count' && (
                  <>
                    <p className="admin-section-desc">ISBN-{isbnType} 선택됨. 몇 권 등록하시겠습니까? (최대 50권)</p>
                    <input
                      className="admin-count-input"
                      type="text"
                      inputMode="numeric"
                      placeholder="권수 입력"
                      value={bookCount}
                      onChange={(e) => setBookCount(e.target.value.replace(/\D/g, ''))}
                      onKeyDown={(e) => { if (e.key === 'Enter') handleCountConfirm() }}
                    />
                    <div className="admin-btn-row">
                      <button className="admin-back-btn" onClick={() => setBookStep('type')}>이전으로</button>
                      <button className="admin-action-btn" onClick={handleCountConfirm}>확인</button>
                    </div>
                  </>
                )}

                {bookStep === 'input' && (
                  <>
                    <p className="admin-section-desc">ISBN-{isbnType} ({isbnList.length}권) — {isbnType}자리 입력</p>
                    <div className="admin-isbn-grid">
                      {isbnList.map((val, idx) => (
                        <input
                          key={idx}
                          className={`admin-isbn-field ${val.length === isbnType ? 'filled' : ''}`}
                          type="text"
                          placeholder={`${idx + 1}번`}
                          value={val}
                          onChange={(e) => handleIsbnChange(idx, e.target.value)}
                          maxLength={isbnType}
                        />
                      ))}
                    </div>
                    <div className="admin-btn-row">
                      <button className="admin-back-btn" onClick={() => { setBookStep('count'); setIsbnList([]) }}>이전으로</button>
                      <button className="admin-action-btn" onClick={handleBulkRegister} disabled={!allFilled || bookLoading}>
                        {bookLoading ? '등록 중...' : '등록하기'}
                      </button>
                    </div>
                  </>
                )}
              </div>
            </div>

            {/* 줄거리 동기화 */}
            <div className="admin-section">
              <h3 className="admin-section-title">줄거리 동기화</h3>
              <p className="admin-section-desc">줄거리가 없는 도서를 알라딘에서 일괄 업데이트합니다.</p>
              <button className="admin-action-btn" onClick={handleSyncDescriptions} disabled={syncLoading}>
                {syncLoading ? '동기화 중...' : '줄거리 동기화'}
              </button>
            </div>
          </div>
        )}

        {activeTab === 'robot' && (
          <div className="admin-tab-content">
            <LiveMap />
          </div>
        )}
      </div>

      {/* 도서 삭제 추후 개발 모달 */}
      {showDeleteNotice && (
        <div className="modal-overlay" onClick={() => setShowDeleteNotice(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close-btn" onClick={() => setShowDeleteNotice(false)}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
            <div className="modal-result">
              <div className="modal-result-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="#aaa" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
                </svg>
              </div>
              <p className="modal-result-text">추후 개발 예정입니다.</p>
              <button className="modal-btn-outline" onClick={() => setShowDeleteNotice(false)}>확인</button>
            </div>
          </div>
        </div>
      )}

      <div className="tab-bar">
        <a className="tab-item" onClick={() => navigate('/home')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" /></svg><span className="tab-label">홈</span></a>
        <a className="tab-item" onClick={() => navigate('/my-library')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /></svg><span className="tab-label">내 서재</span></a>
        <a className="tab-item" onClick={() => navigate('/mypage')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg><span className="tab-label">사용자</span></a>
        <a className="tab-item" onClick={() => navigate('/search')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg><span className="tab-label">검색</span></a>
        <a className="tab-item" onClick={() => navigate('/notifications')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" /></svg><span className="tab-label">알림</span></a>
      </div>
    </div>
  )
}

export default AdminPage
