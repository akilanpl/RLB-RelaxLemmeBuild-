import { Hero } from '@/components/landing/Hero';
import { AgentsSection } from '@/components/landing/AgentsSection';
import { IdePreview } from '@/components/landing/IdePreview';
import { FeaturesSection } from '@/components/landing/FeaturesSection';
import { CommunitySection } from '@/components/landing/CommunitySection';
import { FinalCta } from '@/components/landing/FinalCta';

export default function HomePage() {
  return (
    <div>
      <Hero />
      <AgentsSection />
      <IdePreview />
      <FeaturesSection />
      <CommunitySection />
      <FinalCta />
    </div>
  );
}
