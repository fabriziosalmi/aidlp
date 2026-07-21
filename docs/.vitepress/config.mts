import { defineConfig } from 'vitepress'
import { withMermaid } from 'vitepress-plugin-mermaid'

export default withMermaid(defineConfig({
    title: "AI DLP Proxy",
    description: "Secure LLM Gateway with Data Loss Prevention",
    base: '/aidlp/',
    head: [
    // Everything this site loads is first-party. 'unsafe-inline' is required
    // because VitePress emits an inline appearance script and inline styles.
    // Applied to the built site only: `vitepress dev` serves HMR over a
    // websocket, which a strict connect-src would block as soon as the dev
    // server is not same-origin (--host, or a custom server.hmr.port).
    ...(process.env.NODE_ENV === 'production'
      ? [
          [
            'meta',
            {
              'http-equiv': 'Content-Security-Policy',
              content:
                "default-src 'self'; script-src 'self' 'unsafe-inline'; " +
                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; " +
                "font-src 'self'; connect-src 'self'; base-uri 'self'; form-action 'self'",
            },
          ] as [string, Record<string, string>],
        ]
      : []),
        ['meta', { property: 'og:image', content: '/aidlp/banner.png' }],
        ['meta', { property: 'og:title', content: 'AI DLP Proxy' }],
        ['meta', { property: 'og:description', content: 'Secure Gateway for LLMs with Real-time PII Redaction' }],
        ['link', { rel: 'icon', href: '/aidlp/favicon.ico' }]
    ],
    themeConfig: {
    footer: {
      message:
        '<a href="https://fabriziosalmi.github.io/privacy">Privacy &amp; legal</a>',
    },
        search: {
            provider: 'local'
        },
        nav: [
            { text: 'Home', link: '/' },
            { text: 'Guide', link: '/guide/getting-started' },
            { text: 'Reference', link: '/reference/config' }
        ],

        sidebar: [
            {
                text: 'Introduction',
                items: [
                    { text: 'What is AI DLP Proxy?', link: '/guide/introduction' },
                    { text: 'Architecture', link: '/guide/architecture' },
                    { text: 'Getting Started', link: '/guide/getting-started' },
                    { text: 'Deployment', link: '/guide/deployment' },
                    { text: 'Troubleshooting', link: '/guide/troubleshooting' }
                ]
            },
            {
                text: 'Core Concepts',
                items: [
                    { text: 'Redaction Engine', link: '/concepts/redaction' },
                    { text: 'Secrets Management', link: '/concepts/secrets' }
                ]
            },
            {
                text: 'Configuration',
                items: [
                    { text: 'Config Reference', link: '/reference/config' },
                    { text: 'Metrics', link: '/reference/metrics' }
                ]
            },
            {
                text: 'Project Info',
                items: [
                    { text: 'Contributing', link: '/CONTRIBUTING' },
                    { text: 'Security', link: '/SECURITY' },
                    { text: 'Changelog', link: '/CHANGELOG' },
                    { text: 'Load Testing Report', link: '/load_testing_report' },
                    { text: 'Walkthrough', link: '/walkthrough' }
                ]
            }
        ],

        socialLinks: [
            { icon: 'github', link: 'https://github.com/fabriziosalmi/aidlp' }
        ]
    }
}))
