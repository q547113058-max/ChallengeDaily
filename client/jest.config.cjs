/** Jest 配置 — 前端单元测试 */
const { BACKEND_PORT } = require('./electron/port-config.cjs')

module.exports = {
  testEnvironment: 'jsdom',
  // core.ts 模块加载时即读取 __BACKEND_PORT__（vite define 的等价物）
  globals: {
    __BACKEND_PORT__: BACKEND_PORT,
  },
  setupFilesAfterEnv: ['<rootDir>/jest.setup.ts'],
  moduleNameMapper: {
    '\\.(css|less|scss)$': '<rootDir>/__mocks__/styleMock.cjs',
    '\\.(png|jpg|jpeg|gif|svg|ico)$': '<rootDir>/__mocks__/fileMock.cjs',
    '^@/(.*)$': '<rootDir>/src/$1',
  },
  transform: {
    '^.+\\.(ts|tsx)$': ['babel-jest', {
      presets: [
        ['@babel/preset-env', { targets: { node: 'current' } }],
        ['@babel/preset-react', { runtime: 'automatic' }],
        '@babel/preset-typescript',
      ],
    }],
  },
  testMatch: ['<rootDir>/src/**/*.test.{ts,tsx}'],
}
