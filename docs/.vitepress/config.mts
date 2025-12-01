import { defineConfig } from 'vitepress'

export default defineConfig({
    title: "AI DLP Proxy",
    description: "Secure LLM Gateway with Data Loss Prevention",
    themeConfig: {
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
                    { text: 'Getting Started', link: '/guide/getting-started' }
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
})
