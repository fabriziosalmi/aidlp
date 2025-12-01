import { defineConfig } from 'vitepress'
import { withMermaid } from 'vitepress-plugin-mermaid'

export default withMermaid(defineConfig({
    title: "AI DLP Proxy",
    description: "Secure LLM Gateway with Data Loss Prevention",
    base: '/aidlp/',
    head: [
        ['meta', { property: 'og:image', content: '/aidlp/banner.png' }],
        ['meta', { property: 'og:title', content: 'AI DLP Proxy' }],
        ['meta', { property: 'og:description', content: 'Secure Gateway for LLMs with Real-time PII Redaction' }],
        ['link', { rel: 'icon', href: '/aidlp/favicon.ico' }]
    ],
    themeConfig: {
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
