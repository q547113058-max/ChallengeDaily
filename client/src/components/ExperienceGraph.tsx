import { useMemo } from 'react'
import type { ExperienceProfile } from '../api/profile'

interface Props {
  data: ExperienceProfile
  height?: number
}

/** 项目—技能关系图：左侧项目、右侧技能，连线粗细=某项目经历中该技能出现次数。 */
export default function ExperienceGraph({ data, height = 260 }: Props) {
  const { projects, skills, links, maxWeight } = useMemo(() => {
    const topProjects = (data.projects || []).slice(0, 6).map(p => p.name)
    const topSkills = (data.skills || []).slice(0, 8).map(s => s.name)
    const linkMap = new Map<string, number>()
    for (const ep of data.episodes || []) {
      if (!ep.project || !topProjects.includes(ep.project) || !ep.skills) continue
      for (const sk of ep.skills) {
        if (!topSkills.includes(sk)) continue
        const key = `${ep.project}||${sk}`
        linkMap.set(key, (linkMap.get(key) || 0) + 1)
      }
    }
    const links = Array.from(linkMap.entries()).map(([key, weight]) => {
      const [project, skill] = key.split('||')
      return { project, skill, weight }
    })
    const maxWeight = Math.max(1, ...links.map(l => l.weight))
    return { projects: topProjects, skills: topSkills, links, maxWeight }
  }, [data])

  if (projects.length === 0 || skills.length === 0 || links.length === 0) {
    return (
      <div className="flex items-center justify-center text-xs text-cd-text-tertiary" style={{ height }}>
        经历积累更多后显示项目—技能关系图
      </div>
    )
  }

  const padTop = 20, padBottom = 20
  const usable = height - padTop - padBottom
  const pY = (i: number) => padTop + (i + 0.5) * (usable / projects.length)
  const sY = (i: number) => padTop + (i + 0.5) * (usable / skills.length)
  const leftX = 90, rightX = 300

  return (
    <svg viewBox={`0 0 380 ${height}`} width="100%" height={height} role="img" aria-label="项目与技能关系图">
      {links.map(l => {
        const pIdx = projects.indexOf(l.project)
        const sIdx = skills.indexOf(l.skill)
        if (pIdx < 0 || sIdx < 0) return null
        const op = 0.2 + (l.weight / maxWeight) * 0.5
        const sw = 0.8 + (l.weight / maxWeight) * 3
        return (
          <line key={`${l.project}-${l.skill}`}
            x1={leftX} y1={pY(pIdx)} x2={rightX} y2={sY(sIdx)}
            stroke="var(--cd-green)" strokeOpacity={op} strokeWidth={sw} />
        )
      })}
      {projects.map((p, i) => (
        <text key={p} x={leftX - 6} y={pY(i) + 4} textAnchor="end"
          fontSize="11" fill="var(--cd-text)">{p.length > 12 ? p.slice(0, 11) + '…' : p}</text>
      ))}
      {skills.map((s, i) => (
        <text key={s} x={rightX + 6} y={sY(i) + 4} textAnchor="start"
          fontSize="11" fill="var(--cd-text-secondary)">{s.length > 10 ? s.slice(0, 9) + '…' : s}</text>
      ))}
      <text x={leftX} y={12} textAnchor="middle" fontSize="10" fill="var(--cd-text-tertiary)">项目</text>
      <text x={rightX} y={12} textAnchor="middle" fontSize="10" fill="var(--cd-text-tertiary)">技能</text>
    </svg>
  )
}
