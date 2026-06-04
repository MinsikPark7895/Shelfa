import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import '../styles/AdminPage.css'
import { apiFetch } from '../api'

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

function AdminPage() {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('users')
  const [users, setUsers] = useState<UserItem[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const user = JSON.parse(localStorage.getItem('user') || '{}')
    if (user.role !== 'admin') { navigate('/home'); return }
    if (activeTab === 'users') fetchUsers()
  }, [activeTab])

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
        <button className="admin-nav-btn" onClick={() => navigate('/admin')}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
          </svg>
        </button>
      </div>

      <div className="admin-content">
        <h1 className="admin-title">관리</h1>

        <div className="tab-group">
          <button className={`tab-btn ${activeTab === 'users' ? 'active' : ''}`} onClick={() => setActiveTab('users')}>유저관리</button>
          <button className={`tab-btn ${activeTab === 'books' ? 'active' : ''}`} onClick={() => setActiveTab('books')}>도서관리</button>
          <button className={`tab-btn ${activeTab === 'robot' ? 'active' : ''}`} onClick={() => setActiveTab('robot')}>로봇관리</button>
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
            <div className="admin-empty">API 및 DB 연동 내용</div>
          </div>
        )}

        {activeTab === 'robot' && (
          <div className="admin-tab-content">
            <div className="admin-empty">API 및 DB 연동 내용</div>
          </div>
        )}
      </div>

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
