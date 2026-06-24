import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Home from './pages/Home'
import Login from './pages/Login'
import Register from './pages/Register'
import RegisterComplete from './pages/RegisterComplete'
import MyLibrary from './pages/MyLibrary'
import MyPage from './pages/MyPage'
import Notifications from './pages/Notifications'
import Search from './pages/Search'
import BookDetail from './pages/BookDetail'
import AdminPage from './pages/AdminPage'
import ChatWidget from './components/ChatWidget'
import './App.css'
import ProfileEdit from './pages/ProfileEdit'

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('access_token')
  if (!token) return <Navigate to='/login' replace />
  return children
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/home" element={<PrivateRoute><Home /></PrivateRoute>} />
        <Route path="/" element={<Login />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/register/complete" element={<RegisterComplete />} />
        <Route path="/my-library" element={<PrivateRoute><MyLibrary /></PrivateRoute>} />
        <Route path="/mypage" element={<PrivateRoute><MyPage /></PrivateRoute>} />
        <Route path="/notifications" element={<PrivateRoute><Notifications /></PrivateRoute>} />
        <Route path="/search" element={<PrivateRoute><Search /></PrivateRoute>} />
        <Route path="/book/:id" element={<PrivateRoute><BookDetail /></PrivateRoute>} />
        <Route path="/admin" element={<PrivateRoute><AdminPage /></PrivateRoute>} />
        <Route path="/profile-edit" element={<PrivateRoute><ProfileEdit /></PrivateRoute>} />
      </Routes>
      <ChatWidget />
    </BrowserRouter>
  )
}

export default App
