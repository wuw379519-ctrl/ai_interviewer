"use client";

import { useEffect, useState } from "react";
import { getFeishuStatus, type FeishuPublicConfig } from "@/integrations/feishu";

export const FEISHU_OAUTH_START_HREF = "/api/feishu/oauth/start";

export function shouldShowFeishuLogin(status: FeishuPublicConfig): boolean {
  return Boolean(status.configured && status.loginEnabled);
}

export function FeishuLoginLink() {
  return <a className="button secondary" data-testid="feishu-login-button" href={FEISHU_OAUTH_START_HREF}>
    使用飞书登录
  </a>;
}

export function FeishuLoginButton() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void getFeishuStatus()
      .then((status) => {
        if (!cancelled) setVisible(shouldShowFeishuLogin(status));
      })
      .catch(() => {
        if (!cancelled) setVisible(false);
      });
    return () => { cancelled = true; };
  }, []);

  if (!visible) return null;
  return <FeishuLoginLink />;
}
