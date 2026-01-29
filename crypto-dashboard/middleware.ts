import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

export function middleware(request: NextRequest) {
    // Check if accessing protected dashboard routes
    if (request.nextUrl.pathname.startsWith('/dashboard')) {
        const token = request.cookies.get('auth_token')

        if (!token) {
            // Redirect to login if no token found
            return NextResponse.redirect(new URL('/login', request.url))
        }
    }

    // Allow request to proceed
    return NextResponse.next()
}

export const config = {
    matcher: '/dashboard/:path*',
}
